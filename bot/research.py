"""Bounded local research, using the exact replay engine for every candidate."""

import copy
import itertools
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bot.analytics import analytics
from bot.models import RESOLUTIONS
from bot.settings import Settings
from clients.delta import DeltaError

PARAMETERS = {
    "fast_ema",
    "slow_ema",
    "cmo_length",
    "cmo_threshold",
    "atr_length",
    "macro_sma",
    "sl_atr",
    "tp0",
    "tp1",
    "tp2",
    "trend_fast_period",
    "trend_slow_period",
    "breakout_lookback",
    "breakout_volume_length",
    "breakout_volume_multiplier",
    "breakout_buffer_atr",
    "rsi_length",
    "rsi_oversold",
    "rsi_overbought",
    "rsi_exit_level",
    "rsi_max_ema_gap_atr",
    "smc_swing_length",
    "smc_order_block_lookback",
    "smc_zone_expiry",
    "smc_body_ratio",
    "smc_min_gap_bps",
    "risk_per_trade_percent",
}


class ResearchOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    kind: Literal["single", "multi_coin", "parameters", "walk_forward"] = "single"
    symbols: list[str] = Field(default_factory=list, max_length=12)
    grid: dict[str, list[int | float]] = Field(default_factory=dict)
    objective: Literal["return", "sharpe", "sortino", "calmar"] = "return"
    minimum_trades: int = Field(default=1, ge=0, le=10000)
    train_percent: int = Field(default=60, ge=20, le=80)
    folds: int = Field(default=3, ge=2, le=6)

    @model_validator(mode="after")
    def rules(self):
        if len(self.grid) > 4 or any(key not in PARAMETERS for key in self.grid):
            raise ValueError("Choose up to four supported indicator/risk parameter axes")
        if any(
            not 1 <= len(values) <= 8 or len(set(values)) != len(values)
            for values in self.grid.values()
        ):
            raise ValueError("Each parameter needs one to eight unique values")
        count = math.prod(len(v) for v in self.grid.values())
        if count > 24 or (self.kind == "walk_forward" and count * self.folds > 96):
            raise ValueError("Use at most 24 combinations and 96 walk-forward training runs")
        if self.kind == "parameters" and not self.grid:
            raise ValueError("Choose parameter values to compare")
        if self.kind not in ("parameters", "walk_forward") and self.grid:
            raise ValueError("A parameter grid is only used for comparison or walk-forward tests")
        if self.kind == "multi_coin" and not self.symbols:
            raise ValueError("Enter at least one market for multi-coin comparison")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Remove duplicate markets")
        for symbol in self.symbols:
            Settings(symbol=symbol)
        return self


class Cancelled(Exception):
    pass


def candidates(settings, grid):
    keys = list(grid)
    for values in itertools.product(*(grid[key] for key in keys)):
        parameters = dict(zip(keys, values, strict=True))
        data = settings.model_dump()
        for key, value in parameters.items():
            if key.startswith("tp"):
                data["tp_atr"][int(key[-1])] = float(value)
            else:
                # Grid JSON commonly contains 9.0 for an integer input.
                annotation = Settings.model_fields[key].annotation
                data[key] = int(value) if annotation is int and int(value) == value else value
        try:
            yield parameters, Settings.model_validate(data), None
        except ValueError:
            yield parameters, None, "Combination violates strategy settings"


def score(result, objective, minimum_trades):
    if result["summary"]["trades"] < minimum_trades:
        return None
    if result.get("lookahead_check", {}).get("status") in ("failed", "error"):
        return None
    value = (
        result["summary"]["return_percent"]
        if objective == "return"
        else result["analytics"]["metrics"][objective]
    )
    return value if value is not None and math.isfinite(value) else None


def row_for(index, label, result, parameters=None):
    return {
        "id": index,
        "label": label,
        "symbol": result["settings"]["symbol"],
        "status": "completed",
        "parameters": parameters or {},
        "summary": result["summary"],
        "metrics": result["analytics"]["metrics"],
        "actual_start": result["actual_start"],
        "actual_end": result["actual_end"],
        "candles": result["candles"],
        "lookahead": result["lookahead_check"]["status"],
        "cache": result.get("history", []),
    }


def run_comparison(runner, request, client):
    options = request.research
    multi = options.kind == "multi_coin"
    study = {
        "kind": options.kind,
        "title": "Multi-coin comparison" if multi else "Parameter comparison",
        "rows": [],
        "selected_id": None,
        "objective": options.objective,
        "methodology": (
            "Each market uses its own contract value and available complete history, with the "
            "same starting capital and settings. Contract counts do not equal identical exposure."
            if multi
            else "Rankings are in-sample. Check selected settings on "
            "untouched dates or with walk-forward testing before drawing conclusions."
        ),
        "minimum_trades": options.minimum_trades,
    }
    dataset = None if multi else runner.load_history(request, client)
    runs = (
        [(symbol, None, None) for symbol in options.symbols]
        if multi
        else list(candidates(request.settings, options.grid))
    )
    eligible, first_success = [], None
    for index, (value, settings, error) in enumerate(runs):
        runner.progress(f"Research run {index + 1} of {len(runs)}")
        parameters = {} if multi else value
        label = value if multi else ", ".join(f"{key}={v}" for key, v in parameters.items())
        if error:
            study["rows"].append(
                {
                    "id": index,
                    "label": label,
                    "status": "invalid",
                    "error": error,
                    "parameters": parameters,
                }
            )
            continue
        try:
            if multi:
                settings = Settings.model_validate(
                    {**request.settings.model_dump(), "symbol": value}
                )
            variant = request.model_copy(update={"settings": settings})
            candles, higher, product, history = dataset or runner.load_history(variant, client)
            result = runner.replay(variant, candles, higher, product, history)
            runner.save_result(index, result)
            first_success = index if first_success is None else first_success
            row = row_for(index, label, result, parameters)
            row["score"] = score(result, options.objective, options.minimum_trades)
            row["eligible"] = row["score"] is not None
            if row["eligible"]:
                eligible.append((row["score"], -index, index))
            else:
                row["note"] = "Below minimum trades, undefined metric, or signal check failed"
            study["rows"].append(row)
        except Cancelled:
            raise
        except Exception as exc:
            study["rows"].append(
                {
                    "id": index,
                    "label": label,
                    "status": "error",
                    "parameters": parameters,
                    "error": str(exc)
                    if isinstance(exc, DeltaError)
                    else "Could not complete this market or parameter combination",
                }
            )
        runner.update_study(study)
    selected = max(eligible)[2] if eligible else first_success
    study["selected_id"] = selected
    study["eligible_runs"] = len(eligible)
    return runner.read_result(selected) if selected is not None else None, study


def walk_windows(request):
    interval = RESOLUTIONS[request.settings.timeframe]
    start = (request.start + interval - 1) // interval * interval
    end = request.end // interval * interval
    bars = (end - start) // interval
    train = bars * request.research.train_percent // 100
    remaining = bars - train
    if train < 2 or remaining < request.research.folds * 2:
        raise DeltaError("Choose a longer period for the training window and all test folds")
    boundaries = [
        start + (train + remaining * i // request.research.folds) * interval
        for i in range(request.research.folds + 1)
    ]
    return [(start, boundaries[i], boundaries[i + 1]) for i in range(request.research.folds)]


def clip_history(request, candles, higher):
    interval, hinterval = (
        RESOLUTIONS[request.settings.timeframe],
        RESOLUTIONS[request.settings.higher_timeframe],
    )
    return (
        [
            c
            for c in candles
            if request.start - 600 * interval <= c.time and c.time + interval <= request.end
        ],
        [
            c
            for c in higher
            if request.start // hinterval * hinterval - 600 * hinterval <= c.time
            and c.time + hinterval <= request.end
        ],
    )


def combine_folds(request, results):
    result = copy.deepcopy(results[0])
    result["settings"] = request.settings.model_dump()
    result["request"] = request.model_dump(exclude={"settings"})
    result["actual_end"] = results[-1]["actual_end"]
    result["equity_curve"] = [p for r in results for p in r["equity_curve"]]
    result["trades"] = [{**t, "fold": i + 1} for i, r in enumerate(results) for t in r["trades"]]
    result["candles"] = sum(r["candles"] for r in results)
    result["ambiguous_candles"] = sum(r["ambiguous_candles"] for r in results)
    peak, drawdown = request.initial_balance, 0
    for point in result["equity_curve"]:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
    trades = result["trades"]
    wins = sum(t["net_pnl"] > 0 for t in trades)
    profits = sum(max(t["net_pnl"], 0) for t in trades)
    losses = -sum(min(t["net_pnl"], 0) for t in trades)
    ending = results[-1]["summary"]["ending_equity"]
    result["summary"] = {
        "initial_balance": request.initial_balance,
        "ending_equity": ending,
        "net_pnl": ending - request.initial_balance,
        "return_percent": (ending / request.initial_balance - 1) * 100,
        "max_drawdown_percent": drawdown,
        "trades": len(trades),
        "wins": wins,
        "win_rate": wins / len(trades) * 100 if trades else None,
        "profit_factor": profits / losses if losses else None,
        "gross_profit": profits,
        "gross_loss": losses,
        "fees": sum(r["summary"]["fees"] for r in results),
    }
    result["rejected_entries"] = {}
    for part in results:
        for reason, number in part["rejected_entries"].items():
            result["rejected_entries"][reason] = result["rejected_entries"].get(reason, 0) + number
    result["analytics"] = analytics(result)
    statuses = [r["lookahead_check"]["status"] for r in results]
    result["lookahead_check"] = {
        "status": "failed"
        if any(s in ("failed", "error") for s in statuses)
        else "passed"
        if all(s == "passed" for s in statuses)
        else "limited",
        "samples": sum(r["lookahead_check"].get("samples", 0) for r in results),
        "message": "Signal checks are recorded independently for each selected test fold.",
        "scope": "Sampled checks; skipped folds have no selected strategy to audit.",
    }
    result["walk_forward"] = True
    result["assumptions"] += [
        "Only out-of-sample test folds contribute to this combined curve and trade ledger.",
        "Settings are selected only from expanding earlier training windows.",
        "Each fold starts flat and closes at its boundary; capital carries forward.",
        "Realized-loss budgets restart per fold. Training scores are separate from test returns.",
    ]
    return result


def run_walk_forward(runner, request, client):
    from bot.backtest import simulate

    candles, higher, product, history = runner.load_history(request, client)
    options = request.research
    variants = list(candidates(request.settings, options.grid))
    study = {
        "kind": "walk_forward",
        "title": "Walk-forward validation",
        "rows": [],
        "selected_id": 0,
        "objective": options.objective,
        "minimum_trades": options.minimum_trades,
        "methodology": (
            "Expanding training windows select settings using earlier candles only. Subsequent "
            "non-overlapping test folds are joined with carried capital and flat fold boundaries."
        ),
    }
    results, capital = [], request.initial_balance
    for fold, (train_start, test_start, test_end) in enumerate(walk_windows(request), 1):
        best, trials = None, []
        for candidate, (parameters, settings, error) in enumerate(variants):
            runner.progress(f"Fold {fold}: training combination {candidate + 1} / {len(variants)}")
            if error:
                trials.append({"parameters": parameters, "status": "invalid", "error": error})
                continue
            training = request.model_copy(
                update={"settings": settings, "start": train_start, "end": test_start}
            )
            lower, upper = clip_history(training, candles, higher)
            try:
                trained = runner.replay(training, lower, upper, product, history)
            except Cancelled:
                raise
            except Exception as exc:
                trials.append(
                    {
                        "parameters": parameters,
                        "status": "error",
                        "error": str(exc)
                        if isinstance(exc, DeltaError)
                        else "Could not replay this training combination",
                    }
                )
                continue
            value = score(trained, options.objective, options.minimum_trades)
            trials.append(
                {
                    "parameters": parameters,
                    "status": "completed",
                    "score": value,
                    "summary": trained["summary"],
                    "lookahead": trained["lookahead_check"]["status"],
                }
            )
            if value is not None and (best is None or value > best[0]):
                best = (value, parameters, settings, trained["summary"])
        runner.progress(f"Fold {fold}: replaying untouched test window")
        test = request.model_copy(
            update={
                "start": test_start,
                "end": test_end,
                "initial_balance": capital,
                "settings": best[2] if best else request.settings,
            }
        )
        lower, upper = clip_history(test, candles, higher)
        if best and capital > 0:
            tested = runner.replay(test, lower, upper, product, history)
        else:

            class Flat:
                def evaluate(self, *args):
                    return None

            tested = simulate(test, lower, upper, product, Flat(), runner.progress)
            tested["analytics"] = analytics(tested)
            tested["history"] = history
            tested["lookahead_check"] = {
                "status": "not_run",
                "samples": 0,
                "message": "No eligible training configuration; test fold remained in cash.",
            }
        capital = tested["summary"]["ending_equity"]
        results.append(tested)
        runner.save_result(fold, tested)
        row = row_for(fold, f"Fold {fold}", tested, best[1] if best else {})
        row.update(
            train_start=train_start,
            train_end=test_start,
            train_summary=best[3] if best else None,
            training_trials=trials,
            status="completed" if best else "skipped",
            note=None if best else "No training candidate met eligibility; held cash",
        )
        study["rows"].append(row)
        runner.update_study(study)
        if capital <= 0:
            study["note"] = "Test capital was exhausted; later folds were not executed."
            break
    combined = combine_folds(request, results)
    runner.save_result(0, combined)
    return combined, study
