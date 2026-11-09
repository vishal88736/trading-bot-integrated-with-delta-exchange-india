"""Read-only demo chart preview, independent of execution and account credentials."""

import copy
import threading
import time

from clients.delta import Delta, DeltaError


class MarketPreview:
    def __init__(self, factory=None):
        self.factory = factory
        self.lock = threading.Lock()
        self.cache = {}

    def snapshot(self, settings):
        key = (settings.symbol, settings.timeframe)
        with self.lock:
            cached_at, previous = self.cache.get(key, (0, None))
            if previous and time.monotonic() - cached_at < 15:
                return copy.deepcopy(previous)
            client = None
            try:
                # Explicit empty credentials; this client never submits orders.
                client = self.factory() if self.factory else Delta("", "")
                product = client.product(settings.symbol)
                price = client.ticker(settings.symbol)
                candles = client.candles(settings.symbol, settings.timeframe, count=100)
                record = {
                    "symbol": settings.symbol,
                    "resolution": settings.timeframe,
                    "source": "Delta India demo public market data",
                    "read_only": True,
                    "price": price,
                    "quote": product["quoting_asset"]["symbol"],
                    "candles": [vars(c) for c in candles],
                    "fetched_at": time.time(),
                    "stale": False,
                    "error": None,
                }
            except Exception:
                if previous is None:
                    raise DeltaError("Market preview is unavailable; retry shortly") from None
                record = {**previous, "stale": True, "error": "Market refresh failed"}
            finally:
                if client is not None:
                    client.close()
            self.cache[key] = (time.monotonic(), record)
            if len(self.cache) > 8:
                oldest = min(self.cache, key=lambda k: self.cache[k][0])
                del self.cache[oldest]
            return copy.deepcopy(record)
