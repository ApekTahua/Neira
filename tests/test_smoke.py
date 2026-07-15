import config as cfg


def test_config_importable():
    assert cfg.LOOKBACK_DAYS == 280
