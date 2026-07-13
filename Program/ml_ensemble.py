"""
ml_ensemble.py — Mixture of Experts Ensemble Learning
Adaptasi dari ST-AI-Trading (Sahiltheram) untuk Neira.

Menggunakan 4 model ML:
1. Linear Regression
2. Decision Tree
3. Random Forest
4. Neural Network (MLP)

Ensemble weighting: inverse error (Mixture of Experts)
Bobot di-update secara dinamis setiap hari berdasarkan % error.

Diintegrasikan ke Neira sebagai layer konfirmasi tambahan
untuk screening saham — confidence score di-boost/di-penalty.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler


class MLEnsemble:
    """
    Ensemble Learning — Mixture of Experts.

    Attributes:
        models: list of 4 sklearn models
        weights: array[4] bobot masing-masing model (jumlah = 1)
        scaler: StandardScaler untuk neural network
        feature_cols: list nama kolom fitur
        target_col: nama kolom target (default: 'next_return')
        trained: bool apakah sudah di-fit
        cumulative_errors: array[4] akumulasi absolute % error
        day_count: jumlah hari sudah di-update
    """

    def __init__(self, feature_cols=None, target_col="next_return"):
        self.models = [
            LinearRegression(),
            DecisionTreeRegressor(max_depth=15, random_state=42, min_samples_leaf=5),
            RandomForestRegressor(max_depth=15, random_state=42, n_estimators=100, min_samples_leaf=5),
            MLPRegressor(random_state=42, max_iter=500, hidden_layer_sizes=(64, 32),
                         early_stopping=True, validation_fraction=0.1, n_iter_no_change=10),
        ]
        self.weights = np.array([0.25, 0.25, 0.25, 0.25])  # starting equal
        self.scaler = StandardScaler()
        self.feature_cols = feature_cols
        self.target_col = target_col
        self.trained = False
        self.cumulative_errors = np.array([0.0, 0.0, 0.0, 0.0])
        self.day_count = 0

    def get_feature_cols(self):
        """Default feature columns jika tidak di-set."""
        if self.feature_cols is not None:
            return self.feature_cols
        return [
            "ma10", "ma20", "ma50",
            "bb_bandwidth", "std20",
            "avg_vol_20", "avg_vol_20_prev",
            "rsi", "adx",
            "daily_return", "volume",
            "foreign_net_ma",
        ]

    def prepare_features(self, df):
        """
        Menyiapkan fitur matrix X dari DataFrame.
        - Mengisi NaN dengan 0
        - Standard scaling
        """
        cols = self.get_feature_cols()
        # Filter kolom yang benar-benar ada di df
        avail = [c for c in cols if c in df.columns]
        X = df[avail].copy()
        # Isi NaN
        X = X.fillna(0)
        # Ganti inf
        X = X.replace([np.inf, -np.inf], 0)
        return X, avail

    def create_target(self, df, price_col="close_price", shift=-1):
        """
        Membuat target: return persen 1 hari ke depan.
        target[i] = (close[i+1] / close[i] - 1) * 100
        """
        close = df[price_col]
        target = (close.shift(shift) / close - 1) * 100
        return target.fillna(0)

    def train(self, df, target_series=None):
        """
        Melatih 4 model + hitung bobot awal (inverse error).

        Args:
            df: DataFrame dengan feature columns
            target_series: Series target. Jika None, dibuat otomatis.
        """
        X, avail = self.prepare_features(df)
        y = self.create_target(df) if target_series is None else target_series

        # Hanya baris dengan fitur valid
        valid = y.notna()
        X = X[valid]
        y = y[valid]

        if len(X) < 100:
            print("[ML] Data terlalu sedikit untuk training")
            return

        # Split time-series (chronological, bukan random)
        split = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]

        # Scale ALL features untuk semua model (bukan cuma NN)
        self.scaler.fit(X_train)
        X_train_scaled = self.scaler.transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        errors = []

        for i, model in enumerate(self.models):
            try:
                # Semua model pakai scaled data
                model.fit(X_train_scaled, y_train)
                y_pred = model.predict(X_test_scaled)
                y_train_pred = model.predict(X_train_scaled)

                mse_test = mean_squared_error(y_test, y_pred)
                mse_train = mean_squared_error(y_train, y_train_pred)
                print(f"[ML] Model {i}: MSE test={mse_test:.4f}, train={mse_train:.4f}")
                errors.append(mse_test)
            except Exception as e:
                print(f"[ML] Model {i} gagal training: {e}")
                errors.append(1e6)

        # Bobot awal: inverse error
        errors = np.array(errors)
        total_error = np.sum(errors)
        if total_error > 0 and total_error < 1e10:
            inverse = total_error / errors
            self.weights = inverse / np.sum(inverse)
        else:
            self.weights = np.array([0.25, 0.25, 0.25, 0.25])

        self.trained = True
        print(f"[ML] Bobot awal: {np.round(self.weights, 3)}")
        return self.weights

    def predict(self, features_row):
        """
        Prediksi ensemble untuk satu baris fitur.

        Args:
            features_row: pandas Series — satu baris data

        Returns:
            dict: prediction, confidence, individual predictions
        """
        if not self.trained:
            return {"prediction": 0, "confidence": 0, "details": {}}

        # Siapkan input — pastikan column names preserved
        cols = self.get_feature_cols()
        avail = [c for c in cols if c in features_row.index]
        avail = [c for c in avail if not pd.isna(features_row[c])]

        if len(avail) < 3:
            return {"prediction": 0, "confidence": 0, "details": {}}

        # Build DataFrame with proper column names
        x_df = pd.DataFrame([features_row[avail].values], columns=avail)
        x_df = x_df.fillna(0).replace([np.inf, -np.inf], 0)

        preds = []
        for i, model in enumerate(self.models):
            try:
                x_scaled = self.scaler.transform(x_df)
                p = model.predict(x_scaled)[0]
                preds.append(p)
            except Exception:
                preds.append(0)

        preds = np.array(preds)

        # Ensemble: weighted average
        prediction = float(np.dot(self.weights, preds))

        # Confidence: seberapa kompak prediksi antar model (std rendah = percaya diri)
        std_pred = np.std(preds)
        if abs(prediction) > 0:
            # Signal-to-noise ratio: mean / std
            snr = abs(prediction) / max(std_pred, 0.01)
            confidence = min(snr / 3, 1.0)  # normalisasi: SNR 3+ = confidence 1.0
        else:
            confidence = 0

        return {
            "prediction": prediction,       # % return prediksi
            "confidence": confidence,        # 0-1
            "details": {
                "linear": preds[0],
                "tree": preds[1],
                "forest": preds[2],
                "nn": preds[3],
                "weights": self.weights.copy(),
            }
        }

    def update_weights(self, actual_return, features_row):
        """
        Update bobot berdasarkan % error (Mixture of Experts).
        Dipanggil setiap hari saat actual return diketahui.

        Args:
            actual_return: float — return aktual (%)
            features_row: pandas Series — baris fitur
        """
        if not self.trained:
            return

        self.day_count += 1
        cols = self.get_feature_cols()
        avail = [c for c in cols if c in features_row.index]
        if len(avail) < 3:
            return

        x_df = pd.DataFrame([features_row[avail].values], columns=avail)
        x_df = x_df.fillna(0).replace([np.inf, -np.inf], 0)

        for i, model in enumerate(self.models):
            try:
                x_scaled = self.scaler.transform(x_df)
                pred = model.predict(x_scaled)[0]

                # Percent error
                if abs(actual_return) > 0.001:
                    pct_err = abs(pred - actual_return) / max(abs(actual_return), 0.001)
                else:
                    pct_err = abs(pred - actual_return) * 100

                self.cumulative_errors[i] += min(pct_err, 10)  # cap di 1000%
            except Exception:
                self.cumulative_errors[i] += 1.0  # default error

        # Recalculate weights: inverse of average error
        avg_errors = self.cumulative_errors / max(self.day_count, 1)
        inverse = np.array([1.0 / max(e, 1e-8) for e in avg_errors])
        self.weights = inverse / np.sum(inverse)


def create_ml_score(ensemble, signal_row):
    """
    Menghitung ML score independen (0-100) untuk setiap kandidat saham.
    ML score = prediction_return * confidence, dinormalisasi ke 0-100.

    Args:
        ensemble: MLEnsemble instance (sudah di-train)
        signal_row: pandas Series — satu baris kandidat saham

    Returns:
        float: ML score 0-100. >50 = bullish, <50 = bearish.
    """
    result = ensemble.predict(signal_row)
    pred = result["prediction"]       # % return prediksi (bisa negatif)
    conf = result["confidence"]       # 0-1

    # ML score = seberapa yakin ML bahwa saham akan naik
    # pred = -5% → 0 (bearish), pred = 0% → 50 (netral), pred = +5% → 100 (bullish)
    # Dengan weighting confidence
    raw = 50 + (pred * 10)           # pred=+5% → 100, pred=-5% → 0
    raw = raw * (0.5 + conf * 0.5)   # confidence 0 → raw/2, confidence 1 → raw
    raw = max(0, min(100, raw))      # clamp 0-100

    return raw

    # Rule:
    # ML prediksi naik (>0) dengan confidence tinggi → BOOST
    # ML prediksi turun (<0) → PENALTY
    # ML tidak yakin (conf rendah) → netral
    if conf < 0.3:
        return 1.0  # netral — ML tidak cukup yakin

    if pred > 0.5:
        # ML yakin naik: boost 5–50%
        boost = 1.0 + (conf * min(pred / 3, 0.5))
        return min(boost, 1.5)
    elif pred < -0.3:
        # ML yakin turun: penalty 5–30%
        penalty = 1.0 - (conf * min(abs(pred) / 3, 0.3))
        return max(penalty, 0.7)
    else:
        return 1.0