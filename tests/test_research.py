import json
import math
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from bot.analytics import analytics, html_report, quantstats_report
from bot.backtest import BacktestRequest, Backtests
from bot.history_cache import HistoryCache
from bot.models import RESOLUTIONS, Candle, Signal
from bot.research import Cancelled, ResearchOptions, candidates, walk_windows
from bot.settings import Settings
from bot.strategy_checks import lookahead_check
from clients.delta import DeltaError

START = 1700006400
PRODUCT = {
    "id": 1,
    "contract_value": "1",
    "tick_size": "0.1",
    "quoting_asset": {"symbol": "USD"},
}


class History:
    base_url = "https://fixture.invalid"

    def __init__(self):
        self.calls = []

    def product(self, symbol):
        if symbol == "BADUSD":
            raise DeltaError("No complete history for this fixture market")
        return PRODUCT

    def historical_candles(self, symbol, resolution, start, end, progress=None):
        self.calls.append((symbol, resolution, start, end))
        step = RESOLUTIONS[resolution]
        return [
            Candle(t, 100, 101, 99, 100)
            for t in range((start + step - 1) // step * step, end // step * step, step)
        ]

    def close(self):
        pass


def options(**changes):
    return BacktestRequest(
        settings=Settings(fast_ema=2, slow_ema=4, cmo_length=2, atr_length=2, macro_sma=0),
        start=START,
        end=START + 10 * 86400,
        **changes,
    )


def result_for(request, gain=0.0):
    ending = request.initial_balance * (1 + gain / 100)
    result = {
        "source": "Fixture",
        "settings": request.settings.model_dump(),
        "request": request.model_dump(exclude={"settings"}),
        "quote": "USD",
        "contract": PRODUCT,
        "actual_start": request.start,
        "actual_end": request.end,
        "warmup_candles": 600,
        "candles": (request.end - request.start) // 300,
        "ambiguous_candles": 0,
        "rejected_entries": {},
        "assumptions": [],
        "summary": {
            "initial_balance": request.initial_balance,
            "ending_equity": ending,
            "net_pnl": ending - request.initial_balance,
            "return_percent": gain,
            "max_drawdown_percent": max(-gain, 0),
            "trades": 1,
            "wins": int(gain > 0),
            "win_rate": 100 if gain > 0 else 0,
            "profit_factor": None,
            "gross_profit": max(ending - request.initial_balance, 0),
            "gross_loss": max(request.initial_balance - ending, 0),
            "fees": 0,
        },
        "trades": [
            {"net_pnl": ending - request.initial_balance, "fees": 0, "signal_time": request.start}
        ],
        "equity_curve": [{"time": request.end, "equity": ending}],
        "lookahead_check": {"status": "passed", "samples": 4, "message": "Fixture"},
        "history": [],
    }
    result["analytics"] = analytics(result)
    return result


def test_cache_reuses_rows_fills_gaps_and_separates_source_symbol_resolution(tmp_path):
    cache = HistoryCache(tmp_path / "history.sqlite3")
    client = History()
    first, info = cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900)
    assert len(first) == info["downloaded"] == 3 and info["cached"] == 0
    again, info = cache.fetch(client, "public", "BTCUSD", "5m", START, START + 1500)
    assert again[:3] == first and info["cached"] == 3 and info["downloaded"] == 2
    assert client.calls[-1][2] == START + 900
    count = len(client.calls)
    _, info = cache.fetch(client, "public", "BTCUSD", "5m", START, START + 1500)
    assert info["cached"] == 5 and len(client.calls) == count
    for source, symbol, resolution in [
        ("demo", "BTCUSD", "5m"),
        ("public", "ETHUSD", "5m"),
        ("public", "BTCUSD", "1m"),
    ]:
        _, info = cache.fetch(client, source, symbol, resolution, START, START + 900)
        assert info["cached"] == 0


def test_cache_refresh_bypass_and_unfinished_candles(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.history_cache.time.time", lambda: START + 1000)
    cache, client = HistoryCache(tmp_path / "history.sqlite3"), History()
    cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900)
    rows, info = cache.fetch(
        client, "public", "BTCUSD", "5m", START, START + 1200, policy="refresh"
    )
    assert info["downloaded"] == 3 and rows[-1].time + 300 <= START + 1000
    _, info = cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900, policy="off")
    assert info["cached"] == 0


def test_incomplete_history_never_becomes_a_successful_cache_hit(tmp_path):
    cache, client = HistoryCache(tmp_path / "history.sqlite3"), History()
    original = client.historical_candles
    client.historical_candles = lambda *a: original(*a)[:-1]
    with pytest.raises(DeltaError, match="incomplete"):
        cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900)
    client.historical_candles = original
    _, info = cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900)
    assert info["downloaded"] == 3


def test_corrupt_cached_price_is_refetched(tmp_path):
    cache, client = HistoryCache(tmp_path / "history.sqlite3"), History()
    cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900)
    with sqlite3.connect(cache.path) as db:
        db.execute("UPDATE candles SET close=-1 WHERE time=?", (START + 300,))
    _, info = cache.fetch(client, "public", "BTCUSD", "5m", START, START + 900)
    assert info["cached"] == 2 and info["downloaded"] == 1


def test_daily_metrics_monthly_compounding_and_trade_statistics_stay_distinct():
    start = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    result = result_for(options())
    result.update(
        actual_start=start,
        actual_end=start + 3 * 86400,
        equity_curve=[
            {"time": start + 86400, "equity": 110},
            {"time": start + 2 * 86400, "equity": 99},
            {"time": start + 3 * 86400, "equity": 108.9},
        ],
    )
    result["summary"].update(
        initial_balance=100, ending_equity=108.9, max_drawdown_percent=10, win_rate=0
    )
    data = analytics(result)
    assert [r["return"] for r in data["daily_returns"]] == pytest.approx([0.1, -0.1, 0.1])
    assert data["monthly_returns"][0]["return_percent"] == pytest.approx(8.9)
    assert data["metrics"]["sharpe"] == pytest.approx(math.sqrt(365) / math.sqrt(12))
    assert data["metrics"]["max_drawdown_days"] == 2
    assert data["metrics"]["complete_days"] == 3
    assert result["summary"]["win_rate"] == 0
    json.dumps(data, allow_nan=False)


def test_flat_and_partial_days_produce_no_infinite_ratios():
    result = result_for(options())
    data = analytics(result)
    assert data["metrics"]["sharpe"] is None
    assert data["metrics"]["sortino"] is None
    assert data["metrics"]["complete_days"] <= 1
    assert data["monthly_returns"][0]["partial"]
    json.dumps(data, allow_nan=False)


def test_offline_report_escapes_text_and_contains_no_remote_resources():
    result = result_for(options())
    result["source"] = '<img src=x onerror="bad">'
    report = html_report(result)
    assert "<svg" in report and "Daily Sharpe" in report
    assert "&lt;img" in report and "<img src=x" not in report
    assert "<script" not in report and "https://" not in report


def test_sampled_check_detects_future_dependent_prepared_signals():
    class Leaky:
        def __init__(self, settings):
            pass

        def prepare(self, candles, higher):
            return SimpleNamespace(
                at=lambda index: (
                    Signal("buy", 1, candles[index].time, "future dependent")
                    if index < len(candles) - 1
                    else None
                )
            )

        def evaluate(self, candles, higher):
            return None

    request, client = options(), History()
    lower = client.historical_candles("BTCUSD", "5m", START - 180000, request.end)
    higher = client.historical_candles("BTCUSD", "1h", START - 2160000, request.end)
    checked = lookahead_check(request, lower, higher, {"trades": []}, factory=Leaky)
    assert checked["status"] == "failed" and checked["mismatches"]


def test_grid_bounds_invalid_combinations_and_numeric_types():
    with pytest.raises(ValueError):
        ResearchOptions(kind="parameters", grid={"symbol": [1]})
    with pytest.raises(ValueError):
        ResearchOptions(kind="parameters", grid={"fast_ema": [True]})
    with pytest.raises(ValueError):
        ResearchOptions(
            kind="parameters", grid={"fast_ema": [2, 3, 4, 5, 6], "sl_atr": [1, 2, 3, 4, 5]}
        )
    variants = list(candidates(Settings(fast_ema=2, slow_ema=4), {"fast_ema": [2.0, 5]}))
    assert variants[0][1].fast_ema == 2 and variants[1][1] is None


def test_multi_coin_retains_successes_when_one_market_has_no_history(tmp_path):
    runner = Backtests(
        factory=History, cache_path=tmp_path / "history.sqlite3", artifact_root=tmp_path / "reports"
    )
    runner._run(
        options(
            research=ResearchOptions(
                kind="multi_coin", symbols=["BTCUSD", "BADUSD", "ETHUSD"], minimum_trades=0
            )
        )
    )
    job = runner.snapshot()
    assert job["status"] == "completed"
    assert [r["status"] for r in job["study"]["rows"]] == ["completed", "error", "completed"]
    assert job["result"]["analytics"]["metrics"]["sharpe"] is None
    assert job["result"]["lookahead_check"]["status"] == "passed"
    assert runner.read_result(2, job["run_id"])["settings"]["symbol"] == "ETHUSD"
    with pytest.raises(DeltaError, match="earlier run"):
        runner.read_result(0, "stale-id")


def test_walk_forward_selection_uses_training_only_and_carries_test_capital(tmp_path):
    request = options(
        research=ResearchOptions(
            kind="walk_forward", grid={"fast_ema": [2, 3]}, folds=2, train_percent=60
        )
    )
    windows = walk_windows(request)
    cutoffs = {window[1] for window in windows}
    observed = []
    runner = Backtests(factory=History, artifact_root=tmp_path)

    def controlled(value, candles, higher, product, history):
        assert max(c.time + 300 for c in candles) <= value.end
        assert max(c.time + 3600 for c in higher) <= value.end
        training = value.start == windows[0][0] and value.end in cutoffs
        observed.append((training, value.settings.fast_ema, value.initial_balance))
        # The poorer training candidate would win on future data. It must not be chosen.
        gain = (
            (10 if value.settings.fast_ema == 2 else -10)
            if training
            else (-5 if value.settings.fast_ema == 2 else 50)
        )
        return result_for(value, gain)

    runner.replay = controlled
    runner._run(request)
    job = runner.snapshot()
    assert job["status"] == "completed"
    assert [r["parameters"]["fast_ema"] for r in job["study"]["rows"]] == [2, 2]
    tests = [row for row in observed if not row[0]]
    assert tests == [(False, 2, 10000.0), (False, 2, 9500.0)]
    assert job["result"]["summary"]["ending_equity"] == pytest.approx(9025)
    assert len(job["result"]["trades"]) == 2
    assert job["result"]["actual_start"] == windows[0][1]
    assert job["result"]["walk_forward"] is True


def test_no_eligible_training_configuration_holds_cash(tmp_path):
    runner = Backtests(factory=History, artifact_root=tmp_path)
    runner._run(options(research=ResearchOptions(kind="walk_forward", folds=2)))
    job = runner.snapshot()
    assert job["status"] == "completed"
    assert all(r["status"] == "skipped" for r in job["study"]["rows"])
    assert job["result"]["summary"]["ending_equity"] == 10000
    assert job["result"]["summary"]["trades"] == 0


def test_walk_forward_isolates_a_failed_training_candidate(tmp_path):
    runner = Backtests(factory=History, artifact_root=tmp_path)

    def controlled(request, *args):
        if request.settings.fast_ema == 3:
            raise DeltaError("ATR distances collapse at this tick")
        return result_for(request, 1)

    runner.replay = controlled
    runner._run(
        options(research=ResearchOptions(kind="walk_forward", grid={"fast_ema": [2, 3]}, folds=2))
    )
    job = runner.snapshot()
    assert job["status"] == "completed"
    assert all(r["parameters"] == {"fast_ema": 2} for r in job["study"]["rows"])
    assert all(r["training_trials"][1]["status"] == "error" for r in job["study"]["rows"])


def test_drawdown_duration_includes_the_recovery_candle():
    request = options()
    result = result_for(request)
    result["equity_curve"] = [
        {"time": request.start + 300, "equity": 11000},
        {"time": request.start + 600, "equity": 10000},
        {"time": request.start + 900, "equity": 12000},
    ]
    assert analytics(result)["metrics"]["max_drawdown_days"] == pytest.approx(600 / 86400)


def test_cache_bypass_recovers_from_an_unreadable_database(tmp_path):
    path = tmp_path / "history.sqlite3"
    path.write_text("invalid database")
    runner = Backtests(factory=History, cache_path=path, artifact_root=tmp_path / "reports")
    runner._run(options())
    assert runner.snapshot()["status"] == "error"
    assert "Bypass cache" in runner.snapshot()["message"]
    runner._run(options(cache="off"))
    assert runner.snapshot()["status"] == "completed"
    assert path.read_text() == "invalid database"


def test_cancellation_stops_research_before_additional_work(tmp_path):
    runner = Backtests(factory=History, artifact_root=tmp_path)
    runner.cancel_event.set()
    runner._run(options())
    assert runner.snapshot()["status"] == "cancelled"
    with pytest.raises(Cancelled):
        runner.progress("must not continue")


def test_report_routes_do_not_allow_arbitrary_paths(tmp_path):
    from fastapi.testclient import TestClient

    from bot.web import create_app

    app = create_app(tmp_path)
    runner = app.state.service.backtests
    runner.save_result(0, result_for(options()))
    runner.job["status"] = "completed"
    with TestClient(app) as client:
        path = f"/api/backtests/reports/0?run_id={runner.run_id}"
        report = client.get(path)
        assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
        assert "<svg" in report.text
        assert client.get(path + "&format=unknown").status_code == 422
        assert client.get("/api/backtests/results/0?run_id=wrong").status_code == 409
        assert (
            client.post(
                "/api/backtests",
                json={
                    **options().model_dump(),
                    "research": {"kind": "parameters", "grid": {"api_key": [1]}},
                },
            ).status_code
            == 422
        )


def test_optional_quantstats_export_uses_local_return_series(tmp_path, monkeypatch):
    pytest.importorskip("quantstats")
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("Reports must not download market data")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    request = options()
    result = result_for(request)
    result.update(actual_start=START, actual_end=START + 30 * 86400)
    result["equity_curve"] = [
        {"time": START + (i + 1) * 86400, "equity": 10000 + 10 * i + 20 * math.sin(i)}
        for i in range(30)
    ]
    result["summary"]["ending_equity"] = result["equity_curve"][-1]["equity"]
    result["analytics"] = analytics(result)
    path = tmp_path / "quantstats.html"
    quantstats_report(result, path)
    assert path.exists() and "<svg" in path.read_text()
    assert "DejaVuSans" in path.read_text()


def test_quantstats_ratios_agree_on_the_same_daily_series():
    qs = pytest.importorskip("quantstats")
    import pandas as pd

    request = options()
    result = result_for(request)
    beginning = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    result.update(
        actual_start=beginning,
        actual_end=beginning + 3 * 86400,
        equity_curve=[
            {"time": beginning + (i + 1) * 86400, "equity": price}
            for i, price in enumerate([11000, 9900, 10890])
        ],
    )
    result["summary"].update(ending_equity=10890, max_drawdown_percent=10)
    data = analytics(result)
    series = pd.Series(
        [row["return"] for row in data["daily_returns"]],
        index=pd.date_range("2026-01-01", periods=3),
    )
    assert data["metrics"]["sharpe"] == pytest.approx(qs.stats.sharpe(series, periods=365))
    assert data["metrics"]["sortino"] == pytest.approx(qs.stats.sortino(series, periods=365))
