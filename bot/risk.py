from bot.models import Position
from clients.delta import DeltaError, tick_price


def trade_plan(settings, signal, entry, tick):
    direction = 1 if signal.side == "buy" else -1
    stop = float(tick_price(entry - direction * signal.atr * settings.sl_atr, tick))
    targets = [
        float(tick_price(entry + direction * signal.atr * multiple, tick))
        for multiple in settings.tp_atr
    ]
    if not (
        direction * (entry - stop) > 0
        and all(direction * (b - a) > 0 for a, b in zip([entry] + targets, targets))
    ):
        raise DeltaError("ATR levels collapse at the product tick size; increase target distances")
    quantities = [settings.contracts // 2, settings.contracts // 4]
    quantities.append(settings.contracts - sum(quantities))
    return Position(signal.side, entry, stop, targets, quantities, settings.contracts)


def next_stop(position):
    return position.entry if position.stage == 1 else position.targets[position.stage - 2]
