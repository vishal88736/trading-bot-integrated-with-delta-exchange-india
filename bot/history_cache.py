"""Local, source-separated storage of validated, closed exchange candles."""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from bot.models import RESOLUTIONS, Candle
from clients.delta import DeltaError


class HistoryCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        try:
            with self.connect() as db:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS candles (
                    source TEXT, symbol TEXT, resolution TEXT, time INTEGER,
                    open REAL, high REAL, low REAL, close REAL, volume REAL, fetched_at INTEGER,
                    PRIMARY KEY (source, symbol, resolution, time))"""
                )
        except sqlite3.DatabaseError:
            raise DeltaError("Historical cache is unreadable; choose 'Bypass cache'") from None

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def fetch(self, client, source, symbol, resolution, start, end, progress=None, policy="use"):
        interval = RESOLUTIONS[resolution]
        first = ((start + interval - 1) // interval) * interval
        end = min(end, int(time.time())) // interval * interval
        if first >= end or (end - first) // interval > 530000:
            raise DeltaError("Choose a complete historical range up to one year plus warmup")
        if policy not in ("use", "refresh", "off"):
            raise DeltaError("Unknown history cache policy")
        # Include the upstream host, preventing a testnet candle from satisfying a public request.
        namespace = source + ":" + str(client.base_url)
        stats = {
            "source": source,
            "symbol": symbol,
            "resolution": resolution,
            "policy": policy,
            "requested": (end - first) // interval,
            "cached": 0,
            "downloaded": 0,
            "requests": 0,
            "oldest_fetch": None,
            "latest_fetch": None,
        }
        rows, fetched = {}, []
        try:
            if policy == "use":
                with self.connect() as db:
                    saved = db.execute(
                        """SELECT time, open, high, low, close, volume, fetched_at FROM candles
                        WHERE source=? AND symbol=? AND resolution=? AND time>=? AND time<?""",
                        (namespace, symbol, resolution, first, end),
                    )
                    for row in saved:
                        try:
                            candle = Candle(*row[:6])
                            if (candle.time - first) % interval or type(row[6]) is not int:
                                continue
                            rows[candle.time] = candle
                            fetched.append(row[6])
                        except (ValueError, TypeError):
                            continue
                stats["cached"] = len(rows)
            cursor = first
            while cursor < end:
                if cursor in rows:
                    cursor += interval
                    continue
                boundary = cursor
                while (
                    boundary < end and boundary not in rows and boundary - cursor < 1999 * interval
                ):
                    boundary += interval
                if progress:
                    progress(
                        f"Loading {symbol} {resolution}: {len(rows)} / {stats['requested']} candles"
                    )
                batch = client.historical_candles(symbol, resolution, cursor, boundary, progress)
                expected = list(range(cursor, boundary, interval))
                if [c.time for c in batch] != expected:
                    raise DeltaError(
                        "Historical data is incomplete; no missing candles were invented"
                    )
                # Reconstruct even supplied Candle objects before trusting cached storage.
                batch = [Candle(**vars(c)) for c in batch]
                now = int(time.time())
                if policy != "off":
                    with self.connect() as db:
                        db.executemany(
                            "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [
                                (
                                    namespace,
                                    symbol,
                                    resolution,
                                    c.time,
                                    c.open,
                                    c.high,
                                    c.low,
                                    c.close,
                                    c.volume,
                                    now,
                                )
                                for c in batch
                            ],
                        )
                rows.update((c.time, c) for c in batch)
                fetched.append(now)
                stats["downloaded"] += len(batch)
                stats["requests"] += 1
                cursor = boundary
            if fetched:
                stats["oldest_fetch"], stats["latest_fetch"] = min(fetched), max(fetched)
            return [rows[t] for t in range(first, end, interval)], stats
        except sqlite3.DatabaseError:
            raise DeltaError(
                "Historical cache is unreadable; choose 'Bypass cache' or replace history.sqlite3"
            ) from None
