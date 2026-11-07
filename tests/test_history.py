import pytest

from clients.delta import Delta, DeltaError, PublicHistory


class History(Delta):
    def __init__(self):
        self.calls = 0
        self.omit = None

    def request(self, method, path, **kwargs):
        self.calls += 1
        start, end = kwargs["params"]["start"], kwargs["params"]["end"]
        return [
            {"time": t, "open": 100, "high": 101, "low": 99, "close": 100}
            for t in range(start, end + 1, 300)
            if t != self.omit
        ]


def test_history_pagination_deduplicates_boundaries_and_covers_period():
    client = History()
    bars = client.historical_candles("BTCUSD", "5m", 300000, 300000 + 5000 * 300)
    assert len(bars) == 5000 and client.calls == 3
    assert len({c.time for c in bars}) == 5000


def test_missing_history_is_rejected_instead_of_silently_shortening_a_year():
    client = History()
    client.omit = 300000 + 300
    with pytest.raises(DeltaError, match="Incomplete"):
        client.historical_candles("BTCUSD", "5m", 300000, 300000 + 5000 * 300)
    assert client.calls == 1


@pytest.mark.parametrize(
    "method,path,auth", [("POST", "/v2/orders", False), ("GET", "/v2/wallet/balances", True)]
)
def test_production_history_client_can_never_trade_or_read_accounts(method, path, auth):
    with pytest.raises(DeltaError, match="only unauthenticated"):
        PublicHistory().request(method, path, auth=auth)
