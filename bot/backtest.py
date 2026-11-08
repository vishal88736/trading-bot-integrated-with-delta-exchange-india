"""Candle replay with explicit fills, costs, warmup and no exchange writes."""

import bisect
import copy
import gzip
import json
import tempfile
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bot.models import RESOLUTIONS
from bot.research import Cancelled, ResearchOptions
from bot.risk import entry_size, next_stop, trade_plan
from bot.settings import Settings
from clients.delta import Delta, DeltaError, PublicHistory
from strategies.catalogue import create_strategy, direction_allowed, parameter_keys

HISTORY_WINDOW = 600  # Matches the live runner's indicator history.


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    settings: Settings
    source: Literal["india_public", "demo"] = "india_public"
    start: int = Field(gt=0)
    end: int = Field(gt=0)
    initial_balance: float = Field(default=10000.0, gt=0, le=1000000000)
    fee_bps: float = Field(default=5.0, ge=0, le=100)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)
    cache: Literal["use", "refresh", "off"] = "use"
    check_lookahead: bool = True
    lookahead_samples: int = Field(default=16, ge=4, le=64)
    research: ResearchOptions = Field(default_factory=ResearchOptions)

    @model_validator(mode="after")
    def valid_period(self):
        interval = RESOLUTIONS[self.settings.timeframe]
        if self.end > time.time() or self.end <= self.start:
            raise ValueError("Choose a historical end time after the start time")
        bars = (self.end - self.start) // interval
        if bars < 2 or self.end - self.start > 366 * 86400:
            raise ValueError("Choose at least two candles and a range up to one year (366 days)")
        if self.slippage_bps > self.settings.max_entry_slippage_bps:
            raise ValueError("Test slippage exceeds the strategy's maximum entry slippage")
        if set(self.research.grid) - parameter_keys(self.settings):
            raise ValueError("Parameter grid includes a field unused by the selected strategy")
        if self.research.kind == "walk_forward":
            from bot.research import walk_windows

            try:
                walk_windows(self)
            except DeltaError as exc:
                raise ValueError(str(exc)) from None
        return self


def simulate(request, candles, higher, product, strategy=None, progress=None):
    settings = request.settings
    interval = RESOLUTIONS[settings.timeframe]
    hinterval = RESOLUTIONS[settings.higher_timeframe]
    higher_closes = [c.time + hinterval for c in higher]
    strategy = strategy or create_strategy(settings)
    prepared = strategy.prepare(candles, higher) if hasattr(strategy, "prepare") else None
    multiplier = float(product["contract_value"])
    quote = product["quoting_asset"]["symbol"]
    cash = request.initial_balance
    fee_rate, slip = request.fee_bps / 10000, request.slippage_bps / 10000
    position, pending, trade = None, None, None
    pending_exit = None
    trades, curve, rejected = [], [], Counter()
    fees, peak, max_drawdown = 0.0, cash, 0.0
    ambiguous_bars = set()
    test_indices = [
        i
        for i, c in enumerate(candles)
        if c.time >= request.start and c.time + interval <= request.end
    ]
    if not test_indices:
        raise DeltaError("The selected range contains no complete candles")
    first = test_indices[0]
    hcount = bisect.bisect_right(higher_closes, candles[first].time)
    lower_warmup, higher_warmup = settings.warmup_requirements()
    if first < lower_warmup or hcount < higher_warmup:
        raise DeltaError("Not enough earlier candles to warm up the strategy")

    def close_leg(quantity, reference, timestamp, reason):
        nonlocal cash, fees, position, trade
        direction = 1 if position.side == "buy" else -1
        fill = reference * (1 - direction * slip)
        commission = fill * quantity * multiplier * fee_rate
        pnl = direction * (fill - position.entry) * quantity * multiplier - commission
        cash += pnl
        fees += commission
        trade["net_pnl"] += pnl
        trade["fees"] += commission
        position.remaining -= quantity
        trade["exits"].append(
            {
                "time": timestamp,
                "reason": reason,
                "price": fill,
                "quantity": quantity,
                "net_pnl": pnl,
            }
        )
        if not position.remaining:
            trade.update(exit_time=timestamp, final_reason=reason)
            trades.append(trade)
            position, trade = None, None

    for ordinal, index in enumerate(test_indices):
        candle = candles[index]
        was_in_trade = position is not None
        if pending_exit and position:
            close_leg(position.remaining, candle.open, candle.time, pending_exit)
        pending_exit = None
        if pending:
            direction = 1 if pending.side == "buy" else -1
            entry = candle.open * (1 + direction * slip)
            sizing = entry_size(
                settings,
                pending,
                entry,
                product["tick_size"],
                multiplier,
                max(0, cash),
                max(0, cash),
                request.fee_bps,
            )
            quantity = sizing["quantity"]
            notional = entry * quantity * multiplier
            entry_fee = notional * fee_rate
            if cash - request.initial_balance <= -settings.max_loss_quote or cash <= 0:
                rejected["realized_loss_limit"] += 1
            elif not quantity:
                rejected["risk_budget_or_minimum_size"] += 1
            elif quantity > settings.max_contracts or notional > settings.max_notional_quote:
                rejected["position_limit"] += 1
            elif notional / settings.leverage + entry_fee > cash:
                rejected["insufficient_simulated_funds"] += 1
            else:
                position = trade_plan(settings, pending, entry, product["tick_size"], quantity)
                cash -= entry_fee
                fees += entry_fee
                trade = {
                    "side": position.side,
                    "signal_time": pending.time,
                    "entry_time": candle.time,
                    "entry": entry,
                    "atr": pending.atr,
                    "initial_stop": position.stop,
                    "targets": position.targets[:],
                    "quantity": quantity,
                    "sizing": sizing,
                    "net_pnl": -entry_fee,
                    "fees": entry_fee,
                    "exits": [],
                    "stop_updates": [],
                    "reason": pending.reason,
                }
            pending = None

        traded_this_bar = was_in_trade or position is not None
        if position:
            direction = 1 if position.side == "buy" else -1
            adverse = candle.low if direction == 1 else candle.high
            favorable = candle.high if direction == 1 else candle.low
            if direction * (adverse - position.stop) <= 0:
                if direction * (favorable - position.targets[position.stage]) >= 0:
                    ambiguous_bars.add(candle.time)
                reference = (
                    min(candle.open, position.stop)
                    if direction == 1
                    else max(candle.open, position.stop)
                )
                close_leg(position.remaining, reference, candle.time + interval, "stop")
            else:
                while position and direction * (favorable - position.targets[position.stage]) >= 0:
                    stage = position.stage
                    close_leg(
                        position.quantities[stage],
                        position.targets[stage],
                        candle.time + interval,
                        f"tp{stage + 1}",
                    )
                    if position:
                        position.stage += 1
                        position.stop = next_stop(position, product["tick_size"])
                        trade["stop_updates"].append(
                            {
                                "time": candle.time + interval,
                                "after_target": position.stage,
                                "stop": position.stop,
                            }
                        )
                        # Intrabar ordering is unknown: charge the advanced stop if it
                        # was also inside this candle, before allowing another target.
                        if direction * (adverse - position.stop) <= 0:
                            ambiguous_bars.add(candle.time)
                            close_leg(
                                position.remaining,
                                position.stop,
                                candle.time + interval,
                                "advanced_stop",
                            )

        if (
            position
            and settings.exit_mode != "ladder_only"
            and (hasattr(prepared, "exit_at") or hasattr(strategy, "exit_reason"))
        ):
            end = bisect.bisect_right(higher_closes, candle.time + interval)
            pending_exit = (
                prepared.exit_at(index, position.side)
                if hasattr(prepared, "exit_at")
                else strategy.exit_reason(
                    position.side,
                    candles[max(0, index - HISTORY_WINDOW + 1) : index + 1],
                    higher[max(0, end - HISTORY_WINDOW) : end],
                )
            )
        if not traded_this_bar and ordinal < len(test_indices) - 1:
            end = bisect.bisect_right(higher_closes, candle.time + interval)
            signal = (
                prepared.at(index)
                if prepared
                else strategy.evaluate(
                    candles[max(0, index - HISTORY_WINDOW + 1) : index + 1],
                    higher[max(0, end - HISTORY_WINDOW) : end],
                )
            )
            if signal:
                if signal.time != candle.time:
                    raise DeltaError("Strategy returned a signal for a different candle")
                if direction_allowed(settings, signal.side):
                    pending = signal
                else:
                    rejected["direction_filter"] += 1
        unrealized = 0.0
        if position:
            direction = 1 if position.side == "buy" else -1
            unrealized = (
                direction * (candle.close - position.entry) * position.remaining * multiplier
            )
        equity = cash + unrealized
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
        curve.append({"time": candle.time + interval, "equity": equity})
        if progress and ordinal % 100 == 0:
            progress(f"Replaying candle {ordinal + 1} of {len(test_indices)}")

    if position:
        last = candles[test_indices[-1]]
        close_leg(position.remaining, last.close, last.time + interval, "end_of_test")
        curve[-1]["equity"] = cash
    # Final settlement replaces the last equity sample. Recalculate drawdown
    # from the actual exported curve so an unexported pre-fee peak cannot leak in.
    peak, max_drawdown = request.initial_balance, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        max_drawdown = max(max_drawdown, (peak - point["equity"]) / peak * 100)
    profits = sum(max(t["net_pnl"], 0) for t in trades)
    losses = -sum(min(t["net_pnl"], 0) for t in trades)
    result = {
        "source": "Delta India public market history"
        if request.source == "india_public"
        else "Delta India demo historical candles",
        "contract": {
            "contract_value": product["contract_value"],
            "tick_size": product["tick_size"],
            "product_id": product.get("id"),
            "quote": quote,
        },
        "quote": quote,
        "settings": settings.model_dump(),
        "request": request.model_dump(exclude={"settings"}),
        "actual_start": candles[first].time,
        "actual_end": candles[test_indices[-1]].time + interval,
        "candles": len(test_indices),
        "warmup_candles": first,
        "summary": {
            "initial_balance": request.initial_balance,
            "ending_equity": cash,
            "net_pnl": cash - request.initial_balance,
            "return_percent": (cash / request.initial_balance - 1) * 100,
            "max_drawdown_percent": max_drawdown,
            "trades": len(trades),
            "wins": sum(t["net_pnl"] > 0 for t in trades),
            "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) * 100
            if trades
            else None,
            "profit_factor": profits / losses if losses else None,
            "gross_profit": profits,
            "gross_loss": losses,
            "fees": fees,
        },
        "rejected_entries": dict(rejected),
        "ambiguous_candles": len(ambiguous_bars),
        "trades": trades,
        "equity_curve": curve,
        "assumptions": [
            "Closed-candle signals; entries at the next candle open with adverse slippage.",
            "Enabled strategy exits execute at the next candle open after close confirmation.",
            "Risk sizing reserves stop distance and costs; gaps can exceed planned risk.",
            (
                "Initial stop and targets use the same rounded ATR levels "
                "and allocations as the runner."
            ),
            (
                "Stops take priority when a candle touches both stop and target. "
                "An advanced stop can close the remainder in that same candle."
            ),
            (
                "Target touches fill at the target with adverse slippage; "
                "gaps through stops fill at the worse opening price."
            ),
            (
                "Fees charged on every fill. Funding, tax, liquidation, "
                "spread changes and order-book liquidity are excluded."
            ),
            (
                "Drawdown is sampled at candle closes; "
                "all remaining positions close at the final candle close."
            ),
            (
                "Historical target touches differ from the demo runner's polling; "
                "simulated returns are not exchange execution results."
            ),
            (
                "History source and contract tick sizes are recorded in this report; "
                "public market data is separate from the connected demo account."
            ),
        ],
    }
    return result


class Backtests:
    def __init__(self, factory=None, reference_root=None, cache_path=None, artifact_root=None):
        self.factory = factory
        self.reference_root = reference_root
        self.cache_path = cache_path
        self.temporary = tempfile.TemporaryDirectory() if artifact_root is None else None
        self.artifact_root = Path(artifact_root or self.temporary.name)
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.run_id = uuid.uuid4().hex
        self.results = set()
        self.thread = None
        self.job = {
            "status": "idle",
            "message": "Choose a date range and run a backtest",
            "result": None,
            "study": None,
            "run_id": self.run_id,
        }

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.job)

    def start(self, request):
        with self.lock:
            if self.job["status"] == "running":
                raise DeltaError("A backtest is already running")
            self.cancel_event.clear()
            self.run_id = uuid.uuid4().hex
            self.results = set()
            self.job = {
                "status": "running",
                "message": (
                    "Loading Delta India public historical candles"
                    if request.source == "india_public"
                    else "Loading Delta demo historical candles"
                ),
                "result": None,
                "study": None,
                "run_id": self.run_id,
            }
            self.thread = threading.Thread(target=self._run, args=(request,), daemon=True)
            self.thread.start()
            return copy.deepcopy(self.job)

    def cancel(self):
        with self.lock:
            if self.job["status"] == "running":
                self.cancel_event.set()
                self.job["message"] = "Cancelling after the current data request"
            return copy.deepcopy(self.job)

    def update_study(self, study):
        with self.lock:
            self.job["study"] = copy.deepcopy(study)

    def save_result(self, index, result):
        directory = self.artifact_root / self.run_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f"{index}.json.gz"
        temporary = path.with_suffix(".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            json.dump(result, stream, allow_nan=False, separators=(",", ":"))
        temporary.replace(path)
        self.results.add(index)

    def read_result(self, index, run_id=None):
        if run_id is not None and run_id != self.run_id:
            raise DeltaError("This result belongs to an earlier run; refresh the research page")
        if index not in self.results:
            raise DeltaError("This run has no completed result")
        with gzip.open(self.artifact_root / self.run_id / f"{index}.json.gz", "rt") as stream:
            return json.load(stream)

    def report(self, index, run_id, flavour="html"):
        from bot.analytics import html_report, quantstats_report

        with self.lock:
            if self.job["status"] != "completed":
                raise DeltaError("Wait for the research run to complete before exporting a report")
            result = self.read_result(index, run_id)
            study = copy.deepcopy(self.job.get("study"))
            path = self.artifact_root / self.run_id / f"{index}-{flavour}.html"
            if flavour == "quantstats":
                if not path.exists():
                    quantstats_report(result, path)
            else:
                path.write_text(html_report(result, study), encoding="utf-8")
            return path

    def load_history(self, request, client):
        from bot.history_cache import HistoryCache

        s = request.settings
        product = client.product(s.symbol)
        datasets, stats = [], []
        cache = (
            HistoryCache(self.cache_path) if self.cache_path and request.cache != "off" else None
        )
        for resolution, start in [
            (s.timeframe, request.start - HISTORY_WINDOW * RESOLUTIONS[s.timeframe]),
            (
                s.higher_timeframe,
                request.start // RESOLUTIONS[s.higher_timeframe] * RESOLUTIONS[s.higher_timeframe]
                - HISTORY_WINDOW * RESOLUTIONS[s.higher_timeframe],
            ),
        ]:
            if len(datasets) == 1 and not s.requires_higher_history():
                datasets.append([])
                continue
            self.progress(f"Loading {s.symbol} {resolution} history")
            if cache:
                candles, info = cache.fetch(
                    client,
                    request.source,
                    s.symbol,
                    resolution,
                    start,
                    request.end,
                    self.progress,
                    request.cache,
                )
            else:
                candles = client.historical_candles(
                    s.symbol, resolution, start, request.end, self.progress
                )
                info = {
                    "source": request.source,
                    "symbol": s.symbol,
                    "resolution": resolution,
                    "policy": "off",
                    "cached": 0,
                    "downloaded": len(candles),
                }
            datasets.append(candles)
            stats.append(info)
        return *datasets, product, stats

    def replay(self, request, candles, higher, product, history):
        from bot.analytics import analytics
        from bot.strategy_checks import lookahead_check

        result = simulate(request, candles, higher, product, progress=self.progress)
        result["history"] = history
        result["analytics"] = analytics(result)
        result["lookahead_check"] = (
            lookahead_check(request, candles, higher, result, self.progress)
            if request.check_lookahead
            else {"status": "not_run", "samples": 0, "message": "Disabled for this research run"}
        )
        return result

    def _run(self, request):
        client = None
        try:
            client = (
                self.factory or (PublicHistory if request.source == "india_public" else Delta)
            )()
            if request.research.kind == "single":
                candles, higher, product, history = self.load_history(request, client)
                result = self.replay(request, candles, higher, product, history)
                study, selected = None, 0
            else:
                from bot.research import run_comparison, run_walk_forward

                run = (
                    run_walk_forward if request.research.kind == "walk_forward" else run_comparison
                )
                result, study = run(self, request, client)
                selected = study["selected_id"]
            if result is not None and self.reference_root is not None:
                from bot.reference_checks import validate

                self.progress(
                    "Checking reference statistics and independent bracket execution scenarios"
                )
                result["reference_checks"] = validate(result, self.reference_root)
            if result is not None:
                self.save_result(selected, result)
            self.progress("Finishing research report")
            with self.lock:
                self.job = {
                    "status": "completed",
                    "message": "Backtest complete"
                    if result is not None
                    else "No markets completed; see individual data errors below",
                    "result": result,
                    "study": study,
                    "run_id": self.run_id,
                }
        except Cancelled:
            with self.lock:
                self.job.update(status="cancelled", message="Research cancelled", result=None)
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, DeltaError)
                else "Backtest failed: check history availability and strategy inputs"
            )
            with self.lock:
                self.job.update(status="error", message=message, result=None)
        finally:
            if client is not None:
                client.close()

    def progress(self, message):
        if self.cancel_event.is_set():
            raise Cancelled
        with self.lock:
            self.job["message"] = message
