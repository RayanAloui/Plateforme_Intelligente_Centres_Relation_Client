from crc.forecasting.backtest import folds
from crc.splits import SPLITS


def test_twelve_contiguous_monthly_folds():
    f = folds()
    assert len(f) == 12
    for (_, end), (start, _) in zip(f, f[1:]):
        assert end == start


def test_backtest_never_touches_test_period():
    assert folds()[-1][1] == SPLITS["test"][0]