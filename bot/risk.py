import math

from bot.models import Position
from clients.delta import DeltaError, tick_price


def trade_plan(settings, signal, entry, tick, quantity=None):
    direction = 1 if signal.side == "buy" else -1
    stop = float(tick_price(entry - direction * signal.atr * settings.sl_atr, tick))
    targets = [
        float(tick_price(entry + direction * signal.atr * multiple, tick))
        for multiple in settings.tp_atr
    ]
    if not (
        direction * (entry - stop) > 0
        and all(direction * (b - a) > 0 for a, b in zip([entry] + targets, targets, strict=False))
    ):
        raise DeltaError("ATR levels collapse at the product tick size; increase target distances")
    quantity = settings.contracts if quantity is None else quantity
    if type(quantity) is not int or quantity < 4:
        raise DeltaError("At least four whole contracts are required for the three-part ladder")
    quantities = [quantity // 2, quantity // 4]
    quantities.append(quantity - sum(quantities))
    return Position(signal.side, entry, stop, targets, quantities, quantity)


def next_stop(position, tick):
    price = position.entry if position.stage == 1 else position.targets[position.stage - 2]
    return float(tick_price(price, tick))


def entry_size(settings, signal, price, tick, multiplier, equity, available, fee_bps):
    """Conservative planned-stop sizing, with integer allocation and funding caps."""
    if settings.sizing_mode == "fixed_contracts":
        return {"quantity": settings.contracts, "basis": "fixed_contracts"}
    if not all(math.isfinite(v) and v >= 0 for v in (equity, available, fee_bps)):
        raise DeltaError("Cannot confirm capital and fee inputs for risk sizing")
    direction = 1 if signal.side == "buy" else -1
    stop = float(tick_price(price - direction * signal.atr * settings.sl_atr, tick))
    slip = settings.max_entry_slippage_bps / 10000
    worst_price = price * (1 + slip)
    exit_price = max(price, stop)
    # Reserve adverse execution on entry/exit, tick rounding, and estimated fees.
    unit_risk = (
        abs(price - stop)
        + float(tick)
        + (price + exit_price) * slip
        + (worst_price + exit_price * (1 + slip)) * fee_bps / 10000
    ) * multiplier
    unit_margin = worst_price * multiplier * (1 / settings.leverage + fee_bps / 10000)
    budget = min(equity, available) * settings.risk_per_trade_percent / 100
    quantity = max(
        0,
        math.floor(
            min(
                budget / unit_risk,
                available / unit_margin,
                settings.max_contracts,
                settings.max_notional_quote / (worst_price * multiplier),
            )
        ),
    )
    return {
        "quantity": quantity if quantity >= 4 else 0,
        "basis": "risk_percent",
        "budget_quote": budget,
        "estimated_stop_risk_quote": quantity * unit_risk if quantity >= 4 else 0,
        "risk_per_trade_percent": settings.risk_per_trade_percent,
    }
