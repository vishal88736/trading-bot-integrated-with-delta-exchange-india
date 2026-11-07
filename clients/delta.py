"""India demo REST v2 client, replacing the upstream 2019 v1/legacy socket client."""

import hashlib
import hmac
import json
import math
import re
import time
from decimal import Decimal, ROUND_HALF_UP

import requests

from bot.models import Candle, RESOLUTIONS

DEMO_URL = "https://cdn-ind.testnet.deltaex.org"


class DeltaError(RuntimeError):
    pass


class UncertainOrder(DeltaError):
    pass


def generate_signature(secret, message):
    # Retains the HMAC-SHA256 signing primitive from the original Delta sample.
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def tick_price(price: float, tick: str) -> str:
    step = Decimal(tick)
    value = Decimal(str(price))
    if not step.is_finite() or step <= 0 or not value.is_finite() or value <= 0:
        raise ValueError("Invalid order price/tick")
    rounded = (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    if rounded <= 0:
        raise ValueError("Rounded order price is not positive")
    return format(rounded, "f")


class Delta:
    def __init__(self, api_key="", api_secret="", session=None):
        self.api_key, self.api_secret = api_key, api_secret
        self.session = session or requests.Session()
        self.session.trust_env = False

    def close(self):
        self.session.close()

    def request(self, method, path, *, params=None, body=None, auth=False):
        if method != "GET" and not auth:
            raise DeltaError("Exchange writes require demo credentials")
        if auth and not (self.api_key and self.api_secret):
            raise DeltaError("Enter demo API key and secret in Connection settings")
        for attempt in range(3 if method == "GET" else 1):
            payload = json.dumps(body, separators=(",", ":"), allow_nan=False) if body else ""
            request = requests.Request(
                method,
                DEMO_URL + path,
                params=params,
                data=payload,
                headers={
                    "User-Agent": "delta-india-demo-bot/0.1",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                },
            ).prepare()
            if auth:
                timestamp = str(int(time.time()))
                signature = generate_signature(
                    self.api_secret, method + timestamp + request.path_url + payload
                )
                request.headers.update(
                    {"api-key": self.api_key, "timestamp": timestamp, "signature": signature}
                )
            try:
                response = self.session.send(request, timeout=(3, 15), allow_redirects=False)
            except requests.RequestException:
                if method != "GET":
                    raise UncertainOrder(
                        "Exchange write outcome unknown; reconcile demo account before restarting"
                    ) from None
                if attempt < 2:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise DeltaError("Demo API unavailable after three read attempts") from None
            if method != "GET" and (response.status_code >= 500 or response.is_redirect):
                raise UncertainOrder(
                    "Exchange write outcome unknown; reconcile demo account before restarting"
                )
            if (
                method == "GET"
                and response.status_code in (429, 500, 502, 503, 504)
                and attempt < 2
            ):
                time.sleep(0.5 * (2**attempt))
                continue
            try:
                data = response.json()
            except ValueError:
                error = DeltaError if method == "GET" else UncertainOrder
                raise error("Demo API returned an unreadable response") from None
            if not isinstance(data, dict) or not response.ok or data.get("success") is not True:
                code = data.get("error", {}) if isinstance(data, dict) else {}
                code = (
                    code.get("code", "request_failed")
                    if isinstance(code, dict)
                    else "request_failed"
                )
                code = re.sub(r"[^a-zA-Z0-9_ -]", "", str(code))[:70]
                raise DeltaError(f"Demo API HTTP {response.status_code}: {code}")
            return data.get("result", {})
        raise DeltaError("Demo API read failed")

    def product(self, symbol):
        product = self.request("GET", f"/v2/products/{symbol}")
        if (
            product.get("contract_type") != "perpetual_futures"
            or product.get("notional_type") != "vanilla"
            or product.get("is_quanto")
            or product.get("state") != "live"
            or product.get("trading_status") != "operational"
        ):
            raise DeltaError("This version supports operational linear perpetual futures only")
        for field in ("contract_value", "tick_size"):
            value = float(product[field])
            if not math.isfinite(value) or value <= 0:
                raise DeltaError("Invalid exchange contract metadata")
        return product

    def ticker(self, symbol):
        ticker = self.request("GET", f"/v2/tickers/{symbol}")
        price = float(ticker["close"])
        if not math.isfinite(price) or price <= 0:
            raise DeltaError("Invalid market price")
        timestamp = float(ticker.get("timestamp", 0)) / 1000000
        if not math.isfinite(timestamp) or not -10 <= time.time() - timestamp <= 120:
            raise DeltaError("Demo ticker is stale; runner paused")
        return price

    def candles(self, symbol, resolution, count=600, now=None):
        now = int(time.time()) if now is None else now
        interval = RESOLUTIONS[resolution]
        rows = self.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": symbol,
                "resolution": resolution,
                "start": now - (count + 2) * interval,
                "end": now,
            },
        )
        result = sorted(
            (Candle.parse(row) for row in rows if int(row["time"]) + interval <= now),
            key=lambda c: c.time,
        )
        result = list({c.time: c for c in result}.values())[-count:]
        if not result or now - (result[-1].time + interval) > interval * 2:
            raise DeltaError(f"Missing or stale {resolution} demo candles")
        if any(b.time - a.time != interval for a, b in zip(result, result[1:])):
            raise DeltaError(f"Gaps in {resolution} demo candle history; entries paused")
        return result

    def position(self, product_id):
        return self.request("GET", "/v2/positions", params={"product_id": product_id}, auth=True)

    def open_orders(self, product_id):
        orders = self.request(
            "GET",
            "/v2/orders",
            params={"product_ids": str(product_id), "states": "open,pending", "page_size": 100},
            auth=True,
        )
        if len(orders) >= 100:
            raise DeltaError("Too many open orders for safe demo reconciliation")
        return orders

    def market_order(self, product_id, side, size, client_id, stop=None):
        body = {
            "product_id": product_id,
            "side": side,
            "size": size,
            "order_type": "market_order",
            "client_order_id": client_id,
            "reduce_only": stop is None,
        }
        if stop is not None:
            body.update(
                bracket_stop_loss_price=stop, bracket_stop_trigger_method="last_traded_price"
            )
        return self.request("POST", "/v2/orders", body=body, auth=True)

    def set_leverage(self, product_id, leverage):
        return self.request(
            "POST",
            f"/v2/products/{product_id}/orders/leverage",
            body={"leverage": str(leverage)},
            auth=True,
        )

    def protect(self, product_id, stop):
        # Edit the existing native stop; only one position bracket is allowed.
        for attempt in range(3):
            stops = [
                order
                for order in self.open_orders(product_id)
                if order.get("bracket_order") and order.get("stop_order_type") == "stop_loss_order"
            ]
            if len(stops) == 1:
                receipt = self.request(
                    "PUT",
                    "/v2/orders",
                    body={
                        "id": stops[0]["id"],
                        "product_id": product_id,
                        "stop_price": stop,
                    },
                    auth=True,
                )
                if Decimal(str(receipt.get("stop_price", 0))) != Decimal(stop):
                    raise UncertainOrder("Demo stop update was not confirmed; inspect the account")
                return receipt
            if len(stops) > 1:
                raise DeltaError("Multiple protective stops found; reconcile the demo account")
            if attempt < 2:
                time.sleep(1)
        raise DeltaError("Native demo stop could not be confirmed; inspect the account")
