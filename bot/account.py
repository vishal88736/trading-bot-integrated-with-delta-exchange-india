"""Read-only account snapshots, independent of whether the trading runner is active."""

import copy
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from clients.delta import Delta, DeltaError


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def asset(product, kind="settling_asset"):
    return (product.get(kind) or {}).get("symbol")


def normalize(section, raw):
    rows = raw["rows"] if section == "orders" else raw
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise DeltaError(f"Demo {section} response has an unexpected format")
    result = []
    for row in rows:
        product = row.get("product") or {}
        if section == "balances":
            result.append(
                {
                    "asset": row.get("asset_symbol"),
                    "account_id": row.get("user_id"),
                    **{
                        key: numeric(row.get(key))
                        for key in (
                            "balance",
                            "available_balance",
                            "blocked_margin",
                            "position_margin",
                            "order_margin",
                            "portfolio_margin",
                            "cross_position_margin",
                            "cross_order_margin",
                            "commission",
                            "cross_commission",
                            "cross_locked_collateral",
                            "cross_asset_liability",
                            "unvested_amount",
                        )
                    },
                }
            )
        elif section == "positions":
            if numeric(row.get("size")) == 0:
                continue
            result.append(
                {
                    "symbol": row.get("product_symbol") or product.get("symbol"),
                    "asset": asset(product),
                    "margin_mode": row.get("margin_mode"),
                    **{
                        key: numeric(row.get(key))
                        for key in (
                            "size",
                            "entry_price",
                            "mark_price",
                            "margin",
                            "liquidation_price",
                            "unrealized_pnl",
                            "realized_pnl",
                            "realized_funding",
                        )
                    },
                }
            )
        elif section == "orders":
            result.append(
                {
                    "id": row.get("id"),
                    "symbol": row.get("product_symbol") or product.get("symbol"),
                    "side": row.get("side"),
                    "state": row.get("state"),
                    "order_type": row.get("stop_order_type") or row.get("order_type"),
                    "reduce_only": row.get("reduce_only"),
                    **{
                        key: numeric(row.get(key))
                        for key in (
                            "size",
                            "unfilled_size",
                            "limit_price",
                            "stop_price",
                        )
                    },
                }
            )
        elif section == "fills":
            result.append(
                {
                    "id": row.get("id"),
                    "symbol": row.get("product_symbol") or product.get("symbol"),
                    "side": row.get("side"),
                    "created_at": row.get("created_at"),
                    "asset": row.get("settling_asset_symbol") or asset(product),
                    **{key: numeric(row.get(key)) for key in ("size", "price", "commission")},
                }
            )
    return result


class Account:
    def __init__(self, credentials, factory=Delta):
        self.credentials, self.factory = credentials, factory
        self.lock = threading.RLock()
        self.thread = None
        self.generation = 0
        self.attempted_at = 0
        self.sections = {}

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.attempted_at = 0
            self.sections = {}

    def snapshot(self, force=False):
        credentials = self.credentials()
        with self.lock:
            if not all(credentials):
                return {
                    "status": "disconnected",
                    "refreshing": False,
                    "sections": {},
                    "message": "Add your demo API key and secret to load funds and holdings",
                }
            busy = self.thread is not None and self.thread.is_alive()
            if not busy and time.time() - self.attempted_at >= (3 if force else 15):
                generation = self.generation
                self.attempted_at = time.time()
                self.thread = threading.Thread(
                    target=self._refresh, args=(credentials, generation), daemon=True
                )
                self.thread.start()
                busy = True
            sections = copy.deepcopy(self.sections)
            failed = any(section.get("error") for section in sections.values())
            loaded = any(section.get("updated_at") for section in sections.values())
            status = (
                "partial"
                if failed and loaded
                else "error"
                if failed
                else "connected"
                if len(sections) == 4
                else "loading"
            )
            return {
                "status": status,
                "refreshing": busy,
                "sections": sections,
                "message": (
                    "Account reads refresh every 15 seconds; "
                    "positions may lag the exchange by up to 10 seconds"
                ),
            }

    def _refresh(self, credentials, generation):
        # Each section owns its session: a slow wallet read must not delay positions.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="delta-account") as pool:
            futures = [
                pool.submit(self._refresh_section, credentials, generation, section, operation)
                for section, operation in (
                    ("balances", "balances"),
                    ("positions", "positions"),
                    ("orders", "account_orders"),
                    ("fills", "recent_fills"),
                )
            ]
            for future in futures:
                future.result()

    def _refresh_section(self, credentials, generation, section, operation):
        client = None
        try:
            try:
                client = self.factory(*credentials)
                raw = getattr(client, operation)()
                data = {
                    "rows": normalize(section, raw),
                    "updated_at": int(time.time()),
                    "error": None,
                    "truncated": section == "orders" and raw["truncated"],
                }
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, DeltaError)
                    else f"Could not read demo {section}"
                )
                for secret in credentials:
                    if secret:
                        message = message.replace(secret, "[redacted]")
                with self.lock:
                    data = {**self.sections.get(section, {}), "error": message}
            with self.lock:
                if generation == self.generation:
                    self.sections[section] = data
        finally:
            if client is not None:
                client.close()
