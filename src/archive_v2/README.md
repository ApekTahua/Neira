# Archived: V2 HMM era + dead-end ML research

Moved here 2026-08-11, not deleted -- full git history preserved
(`git log --follow -- src/archive_v2/<file>` shows the pre-move history).
Confirmed via import-graph grep before moving, not by filename guess
(see `docs/MASTERPLAN.md`'s "CORRECTION 2026-08-10" entry for why that
distinction matters -- a filename-based "looks old" guess already
caused one real incident this session).

**Nothing outside this folder imports anything in it.** `strategy.py`
and `hmm_model.py` stayed in `src/` even though they're also V2-era --
`backtest_v3.py`/`backtest.py`/`screener.py` all still import
`strategy.py`, and `strategy.py` itself imports `hmm_model`, so both
remain load-bearing despite the HMM regime signal no longer being V3's
active entry rule.

Two groups:
- `backtest_v2*.py`, `screener_v2.py`, `train_hmm.py` -- the original
  HMM regime-gate approach, superseded (see `docs/V3_FINDINGS_LOG.md`:
  99%+ concentrated in 5 microcap trades, not a real distributed edge).
- `phase0e_ml_combined_model.py` through `phase0i_significance_test.py`
  -- a self-contained ML/interaction-model research cluster (only
  import each other, not the still-active `phase0_signal_validation.py`/
  `phase0b`/`phase0c`/`phase0d`, which stayed in `src/` because
  `backtest_v3.py` genuinely imports those).

**Not verified to still run.** These files `import hmm_model` /
`from strategy import ...` assuming `src/` is on `sys.path` -- true
when they lived in `src/` directly, not guaranteed now that they're one
directory deeper. If reviving one, add
`sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`
before its other imports.
