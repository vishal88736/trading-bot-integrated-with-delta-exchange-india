import json
import math
import time
import uuid
from pathlib import Path

from bot.models import RESOLUTIONS, State
from bot.risk import next_stop, trade_plan
from bot.settings import Settings, atomic_json
from clients.delta import Delta, DeltaError, UncertainOrder, contract_size, tick_price
from strategies.custom_strategy import CustomStrategy
from strategies.trend_signals import TrendSignals


class Engine:
    def __init__(self, settings: Settings, client: Delta, root: Path):
        self.settings, self.client, self.root = settings, client, root
        self.path = root / f"{settings.mode}-{settings.symbol}.json"
        try:
            self.state = (
                State.parse(json.loads(self.path.read_text())) if self.path.exists() else State()
            )
        except (OSError, ValueError, TypeError):
            raise DeltaError(
                "Saved trade state is invalid; inspect the runtime before restarting"
            ) from None
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
        if not isinstance(data, dict) or "size" not in data:
            raise DeltaError("Demo position response cannot confirm the account quantity")
        actual = contract_size(data["size"])
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
            valid = False
            if len(stops) == 1 and len(orders) == 1:
                stop = stops[0]
                try:
                    stop_price = float(stop["stop_price"])
                    valid = (
                        math.isfinite(stop_price)
                        and stop_price > 0
                        and abs(stop_price - p.stop) <= float(self.tick) / 2
                        and stop.get("side", "sell" if p.side == "buy" else "buy")
                        == ("sell" if p.side == "buy" else "buy")
                        and stop.get("reduce_only", True) is True
                        and stop.get("state", "pending") in ("open", "pending")
                        # Delta brackets close the entire position; their size
                        # is not a standalone-order coverage requirement.
                        and str(stop.get("product_id", self.product_id)) == str(self.product_id)
                    )
                except (KeyError, TypeError, ValueError, DeltaError):
                    valid = False
            if not valid:
                raise DeltaError(
                    "Native protective stop price or metadata is unconfirmed; inspect demo account"
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
            if not isinstance(receipt, dict):
                raise ValueError
            price = float(receipt["average_fill_price"])
            fee = float(receipt["paid_commission"])
            complete = (
                contract_size(receipt["size"]) == quantity
                and contract_size(receipt["unfilled_size"]) == 0
                and receipt["state"] == "closed"
                and receipt.get("side") == side
                and str(receipt.get("product_id")) == str(self.product_id)
                and receipt.get("client_order_id") == self.state.pending["client_id"]
                and receipt.get("reduce_only") is (stop is None)
            )
            if (
                not complete
                or not math.isfinite(price)
                or price <= 0
                or not math.isfinite(fee)
                or isinstance(receipt["average_fill_price"], bool)
                or isinstance(receipt["paid_commission"], bool)
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, DeltaError):
            raise UncertainOrder(
                "Demo fill was incomplete or unconfirmed; reconcile the account"
            ) from None
        return price, fee

    def protect(self, stop):
        stop = float(tick_price(stop, self.tick))
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
        plan = trade_plan(s, signal, price, self.tick)
        if (
            s.contracts > s.max_contracts
            or price * s.contracts * self.multiplier > s.max_notional_quote
        ):
            self.event("risk_block", reason="Position or quote-notional limit exceeded")
            return
        if s.mode == "demo":
            self.exchange_action("set_leverage", leverage=s.leverage)
            self.client.set_leverage(self.product_id, s.leverage)
            self.state.pending = None
            self.save()
        fill, fee = self.fill(signal.side, s.contracts, price, tick_price(plan.stop, self.tick))
        if abs(fill - price) / price * 10000 > s.max_entry_slippage_bps:
            raise UncertainOrder(
                "Demo entry exceeded configured slippage; native initial SL remains, reconcile"
            )
        self.state.position = trade_plan(s, signal, fill, self.tick)
        self.state.realized_quote -= fee
        self.protect(self.state.position.stop)
        self.event(
            "entry",
            side=signal.side,
            price=fill,
            quantity=s.contracts,
            stop=self.state.position.stop,
            targets=self.state.position.targets,
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
                new_stop = next_stop(p, self.tick)
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
