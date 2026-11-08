import pytest

from bot.indicators import cmo


@pytest.mark.parametrize(
    "prefix",
    [
        [100000.000001, 1.000002, 23000.03, 0.000001, 99999.99999, 42.1],
        [0.000001, 100000000.03, 0.000002, 0.000004],
    ],
)
def test_cmo_returns_to_zero_after_a_flat_window(prefix):
    values = prefix + [20.0] * 50
    assert cmo(values, 14)[-10:] == [0.0] * 10
