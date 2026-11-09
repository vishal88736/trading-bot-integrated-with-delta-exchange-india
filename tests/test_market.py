import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from bot.market import MarketPreview
from bot.models import Candle
from bot.settings import Settings, atomic_json
from bot.web import create_app
from clients.delta import DeltaError


class PublicDemo:
    def __init__(self):
        self.calls = []
        self.failed = False

    def product(self, symbol):
        self.calls.append(("product", symbol))
        if self.failed:
            raise RuntimeError("private transport details")
        return {"quoting_asset": {"symbol": "USD"}}

    def ticker(self, symbol):
        self.calls.append(("ticker", symbol))
        return 103.0

    def candles(self, symbol, resolution, count):
        self.calls.append(("candles", symbol, resolution, count))
        return [Candle(1728000000, 100, 104, 99, 103, 5)]

    def close(self):
        self.calls.append(("close",))


def test_market_preview_has_empty_credentials_and_does_not_touch_trading(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    settings = Settings(mode="demo", symbol="ETHUSD")
    atomic_json(tmp_path / "settings.json", settings.model_dump())
    atomic_json(
        tmp_path / "credentials.json", {"api_key": "private-key", "api_secret": "private-secret"}
    )
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    provider = PublicDemo()

    def no_credentials(key, secret):
        assert key == secret == ""
        return provider

    monkeypatch.setattr("bot.market.Delta", no_credentials)
    with TestClient(app) as client:
        response = client.get("/api/market")
        assert response.status_code == 200
        data = response.json()
        assert data["read_only"] and data["symbol"] == "ETHUSD"
        assert data["price"] == 103 and len(data["candles"]) == 1
        assert "private" not in response.text and not data["stale"]
        assert not client.get("/api/status").json()["running"]
    assert provider.calls == [
        ("product", "ETHUSD"),
        ("ticker", "ETHUSD"),
        ("candles", "ETHUSD", "5m", 100),
        ("close",),
    ]
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == before


def test_preview_cache_isolated_by_market_and_timeframe_and_returns_copies(monkeypatch):
    provider = PublicDemo()
    preview = MarketPreview(lambda: provider)
    first = preview.snapshot(Settings())
    first["candles"][0]["close"] = -1
    assert preview.snapshot(Settings())["candles"][0]["close"] == 103
    assert len(provider.calls) == 4
    preview.snapshot(Settings(symbol="ETHUSD"))
    preview.snapshot(Settings(timeframe="15m"))
    assert len(provider.calls) == 12


def test_failed_preview_refresh_labels_cached_data_stale(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("bot.market.time.monotonic", lambda: clock[0])
    provider = PublicDemo()
    preview = MarketPreview(lambda: provider)
    first = preview.snapshot(Settings())
    clock[0] += 16
    provider.failed = True
    stale = preview.snapshot(Settings())
    assert stale["stale"] and stale["fetched_at"] == first["fetched_at"]
    assert stale["price"] == first["price"]
    assert stale["error"] == "Market refresh failed" and "private" not in str(stale)
    provider.failed = False
    clock[0] += 16
    assert not preview.snapshot(Settings())["stale"]


def test_missing_preview_has_a_safe_retry_error():
    provider = PublicDemo()
    provider.failed = True
    preview = MarketPreview(lambda: provider)
    with pytest.raises(DeltaError, match="Market preview is unavailable"):
        preview.snapshot(Settings())
    assert provider.calls[-1] == ("close",)


def test_slow_market_read_does_not_hold_runner_status_lock(tmp_path):
    app = create_app(tmp_path)
    entered, release = threading.Event(), threading.Event()
    provider = PublicDemo()
    original = provider.ticker

    def delayed(symbol):
        entered.set()
        assert release.wait(timeout=5)
        return original(symbol)

    provider.ticker = delayed
    app.state.service.market.factory = lambda: provider
    with TestClient(app) as client, ThreadPoolExecutor(2) as executor:
        pending = executor.submit(client.get, "/api/market")
        assert entered.wait(timeout=3)
        try:
            status = executor.submit(client.get, "/api/status").result(timeout=2)
            assert status.status_code == 200 and not status.json()["running"]
        finally:
            release.set()
        assert pending.result(timeout=3).status_code == 200
