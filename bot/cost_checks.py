"""Cost sensitivity on frozen rules and the exact selected dataset; no network IO."""

from bot.models import Candle


def unpack(result, inputs):
    from bot.backtest import BacktestRequest

    request = BacktestRequest.model_validate({**result["request"], "settings": result["settings"]})
    return (
        request,
        [Candle(**c) for c in inputs["candles"]],
        [Candle(**c) for c in inputs["higher"]],
        inputs["product"],
    )


def selected_runs(result, inputs):
    return (
        inputs["folds"]
        if inputs and "folds" in inputs
        else [{"result": result, "inputs": inputs, "held_cash": False}]
    )


def stress_costs(result, inputs, progress=None):
    from bot.backtest import simulate

    costs = result["request"].get("cost_stress_bps", [])
    scope = (
        "Same data and frozen selected rules; taker fees and spread stay unchanged. "
        "Walk-forward folds carry each scenario's capital without reselecting parameters. "
        "These slippage assumptions do not model market depth or actual exit liquidity."
    )
    if not costs:
        return {"status": "disabled", "scenarios": [], "scope": scope}
    runs = selected_runs(result, inputs)
    if any(not r["inputs"] for r in runs):
        return {"status": "unavailable", "scenarios": [], "scope": scope}
    scenarios = []
    for cost in costs:
        if progress:
            progress(f"Testing execution costs at {cost:g} bps slippage")
        row = {"slippage_bps": cost}
        if any(
            cost + r["result"]["request"].get("spread_bps", 0) / 2
            > r["result"]["settings"]["max_entry_slippage_bps"]
            for r in runs
        ):
            row.update(status="skipped", message="Exceeds the configured entry execution limit")
            scenarios.append(row)
            continue
        capital = initial = result["summary"]["initial_balance"]
        peak, drawdown, fees, trades = initial, 0.0, 0.0, 0
        for run in runs:
            request, lower, higher, product = unpack(run["result"], run["inputs"])
            request = request.model_copy(update={"slippage_bps": cost, "initial_balance": capital})
            if run["held_cash"]:
                continue
            replayed = simulate(request, lower, higher, product, progress=progress)
            for point in replayed["equity_curve"]:
                peak = max(peak, point["equity"])
                drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
            capital = replayed["summary"]["ending_equity"]
            fees += replayed["summary"]["fees"]
            trades += replayed["summary"]["trades"]
            if capital <= 0:
                row.update(status="capital_exhausted", message="Scenario exhausted its capital")
                break
        row.update(
            status=row.get("status", "completed"),
            ending_equity=capital,
            net_pnl=capital - initial,
            return_percent=(capital / initial - 1) * 100,
            max_drawdown_percent=drawdown,
            fees=fees,
            trades=trades,
        )
        scenarios.append(row)
    return {"status": "completed", "scenarios": scenarios, "scope": scope}
