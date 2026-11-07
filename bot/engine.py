import json
import math
import time
import uuid
from pathlib import Path

from bot.models import Position, RESOLUTIONS, State
from bot.settings import Settings, atomic_json
from clients.delta import Delta, DeltaError, UncertainOrder, tick_price
from strategies.custom_strategy import CustomStrategy
from strategies.trend_signals import TrendSignals


class Engine:
    def __init__(self, settings: Settings, client: Delta, root: Path):
        self.settings, self.client, self.root = settings, client, root
        self.path = root / f"{settings.mode}-{settings.symbol}.json"
        self.state = (
            State.parse(json.loads(self.path.read_text())) if self.path.exists() else State()
        )
        if self.state.signature != settings.signature():
            if self.state.position or self.state.pending:
                raise DeltaError(
                    "An existing trade needs its original settings or flat-account reconciliation"
                )
            self.state.signature = settings.signature()
            self.state.last_candle = 0
        if self.state.pending:
            raise UncertainOrder("An unfinished exchange action needs flat-account reconciliation")
        self.strategy = (TrendSignals if settings.strategy == "trend_signals" else CustomStrategy)(
            settings
        )
        self.product = client.product(settings.symbol)
        self.multiplier = float(self.product["contract_value"])
        self.tick = self.product["tick_size"]
        self.product_id = self.product["id"]
        self.quote = self.product["quoting_asset"]["symbol"]
        self.candles = []
        self.price = None
        self.save()

    def save(self):
        atomic_json(self.path, self.state.to_dict())

    def event(self, kind, **values):
        event = {"time": int(time.time()), "kind": kind, **values}
        self.state.events = (self.state.events + [event])[-200:]
        self.save()

    def check_account(self):
        if self.settings.mode == "paper":
            return
        data = self.client.position(self.product_id)
        actual = int(data.get("size", 0))
        p = self.state.position
        expected = p.remaining * (1 if p.side == "buy" else -1) if p else 0
        if actual != expected:
            raise DeltaError(
                "Demo position differs from local state. Confirm flat in Delta, then Reconcile"
            )
        orders = self.client.open_orders(self.product_id)
        if orders and (p is None or any(not o.get("bracket_order") for o in orders)):
            raise DeltaError(
                "Unmanaged demo orders exist for this product; resolve them in Delta first"
            )
        if p:
            stops = [o for o in orders if o.get("stop_order_type") == "stop_loss_order"]
            if (
                len(stops) != 1
                or abs(float(stops[0].get("stop_price", 0)) - p.stop) > float(self.tick) / 2
            ):
                raise DeltaError(
                    "Native protective stop differs from local state; inspect demo account"
                )

    def exchange_action(self, operation, **details):
        # Persist intent BEFORE a write. Never silently repeat an ambiguous write on restart.
        self.state.pending = {"operation": operation, "client_id": uuid.uuid4().hex, **details}
        self.save()

    def fill(self, side, quantity, reference, stop=None):
        if self.settings.mode == "paper":
            fee = reference * quantity * self.multiplier * self.settings.paper_fee_bps / 10000
            return reference, fee
        self.exchange_action("entry" if stop is not None else "exit", side=side, quantity=quantity)
        receipt = self.client.market_order(
            self.product_id, side, quantity, self.state.pending["client_id"], stop
        )
        try:
            price = float(receipt["average_fill_price"])
            fee = float(receipt.get("paid_commission", 0))
            complete = (
                int(receipt["size"]) == quantity
                and int(receipt["unfilled_size"]) == 0
                and receipt["state"] == "closed"
            )
            if not complete or not math.isfinite(price) or price <= 0 or not math.isfinite(fee):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise UncertainOrder(
                "Demo fill was incomplete or unconfirmed; reconcile the account"
            ) from None
        return price, fee

    def protect(self, stop):
        if self.settings.mode == "demo":
            self.exchange_action("move_stop", stop=stop)
            self.client.protect(self.product_id, tick_price(stop, self.tick))
        self.state.position.stop = stop
        self.state.pending = None
        self.save()

    def open(self, signal, price):
        s = self.settings
        if self.state.position or self.state.realized_quote <= -s.max_loss_quote:
            return
        sign = 1 if signal.side == "buy" else -1
        stop = float(tick_price(price - sign * signal.atr * s.sl_atr, self.tick))
        targets = [float(tick_price(price + sign * signal.atr * x, self.tick)) for x in s.tp_atr]
        if (
            s.contracts > s.max_contracts
            or price * s.contracts * self.multiplier > s.max_notional_quote
        ):
            self.event("risk_block", reason="Position or quote-notional limit exceeded")
            return
        if not (
            sign * (price - stop) > 0
            and all(sign * (b - a) > 0 for a, b in zip([price] + targets, targets))
        ):
            raise DeltaError(
                "ATR levels collapse at the product tick size; increase target distances"
            )
        if s.mode == "demo":
            self.exchange_action("set_leverage", leverage=s.leverage)
            self.client.set_leverage(self.product_id, s.leverage)
            self.state.pending = None
            self.save()
        fill, fee = self.fill(signal.side, s.contracts, price, tick_price(stop, self.tick))
        if abs(fill - price) / price * 10000 > s.max_entry_slippage_bps:
            raise UncertainOrder(
                "Demo entry exceeded configured slippage; native initial SL remains, reconcile"
            )
        stop = float(tick_price(fill - sign * signal.atr * s.sl_atr, self.tick))
        targets = [float(tick_price(fill + sign * signal.atr * x, self.tick)) for x in s.tp_atr]
        quantities = [s.contracts // 2, s.contracts // 4]
        quantities.append(s.contracts - sum(quantities))
        self.state.position = Position(signal.side, fill, stop, targets, quantities, s.contracts)
        self.state.realized_quote -= fee
        self.protect(stop)
        self.event(
            "entry",
            side=signal.side,
            price=fill,
            quantity=s.contracts,
            stop=stop,
            targets=targets,
            reason=signal.reason,
        )

    def close_quantity(self, quantity, price, reason):
        p = self.state.position
        side = "sell" if p.side == "buy" else "buy"
        fill, fee = self.fill(side, quantity, price)
        sign = 1 if p.side == "buy" else -1
        pnl = sign * (fill - p.entry) * quantity * self.multiplier - fee
        self.state.realized_quote += pnl
        p.remaining -= quantity
        if not p.remaining:
            self.state.position = None
            self.state.pending = None
        return {"price": fill, "quantity": quantity, "pnl_quote": pnl}

    def manage(self, price):
        p = self.state.position
        if not p:
            return
        sign = 1 if p.side == "buy" else -1
        if sign * (price - p.stop) <= 0:
            details = self.close_quantity(p.remaining, price, "stop_exit")
            self.event("stop_exit", **details)
            return
        while self.state.position and p.stage < 3 and sign * (price - p.targets[p.stage]) >= 0:
            stage = p.stage
            details = self.close_quantity(p.quantities[stage], price, f"tp{stage + 1}")
            p.stage += 1
            if self.state.position:
                # TP1 -> entry, TP2 -> TP1. TP3 closes the final allocation.
                new_stop = p.entry if p.stage == 1 else p.targets[p.stage - 2]
                self.protect(new_stop)
                self.event("stop_moved", stage=p.stage, stop=new_stop)
            self.event(f"tp{stage + 1}", **details)

    def step(self):
        self.check_account()
        price = self.client.ticker(self.settings.symbol)
        self.price = price
        had_position = self.state.position is not None
        self.manage(price)
        now = int(time.time())
        candles = self.client.candles(self.settings.symbol, self.settings.timeframe, now=now)
        self.candles = candles
        latest = candles[-1]
        if latest.time <= self.state.last_candle:
            return
        # Mark every inspected close, including closes processed while a trade is open.
        self.state.last_candle = latest.time
        self.save()
        if had_position or self.state.position:
            return
        age = now - latest.time - RESOLUTIONS[self.settings.timeframe]
        if age > max(30, self.settings.poll_seconds * 2):
            return  # Do not enter a historical signal when starting/recovering mid-candle.
        higher = self.client.candles(self.settings.symbol, self.settings.higher_timeframe, now=now)
        signal = self.strategy.evaluate(candles, higher)
        if signal:
            if signal.time != latest.time:
                raise DeltaError("Strategy returned a signal for a different candle")
            self.open(signal, price)
