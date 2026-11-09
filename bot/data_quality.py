"""Fail closed on incomplete replay inputs and identify the exact data used."""

import hashlib
import json
import struct
from pathlib import Path

from bot.models import RESOLUTIONS, Candle
from clients.delta import DeltaError

ROOT = Path(__file__).resolve().parents[1]
CODE_SHA256 = hashlib.sha256(
    b"".join(
        path.relative_to(ROOT).as_posix().encode() + path.read_bytes()
        for folder in ("bot", "strategies", "clients")
        for path in sorted((ROOT / folder).glob("*.py"))
    )
).hexdigest()


def inspect_data(request, candles, higher, product):
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            [
                request.source,
                request.settings.symbol,
                request.settings.timeframe,
                request.settings.higher_timeframe,
                product["contract_value"],
                product["tick_size"],
                product["quoting_asset"]["symbol"],
            ],
            separators=(",", ":"),
        ).encode()
    )
    datasets = []
    for label, bars, resolution in (
        ("signal", candles, request.settings.timeframe),
        ("higher", higher, request.settings.higher_timeframe),
    ):
        interval = RESOLUTIONS[resolution]
        digest.update(label.encode())
        previous = None
        for bar in bars:
            # Revalidate objects supplied by custom clients or callers, too.
            try:
                Candle(**vars(bar))
            except (ValueError, TypeError):
                raise DeltaError(f"Invalid {label} candle; replay was stopped") from None
            if bar.time % interval or (previous is not None and bar.time - previous != interval):
                raise DeltaError(
                    f"{label.capitalize()} history has gaps, duplicates, or out-of-order candles"
                )
            if bar.time + interval > request.end:
                raise DeltaError(f"{label.capitalize()} history contains an unclosed candle")
            digest.update(
                struct.pack(">q5d", bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume)
            )
            previous = bar.time
        if bars:
            datasets.append(
                {
                    "kind": label,
                    "resolution": resolution,
                    "bars_including_warmup": len(bars),
                    "zero_volume_bars": sum(c.volume == 0 for c in bars),
                    "first": bars[0].time,
                    "last_close": bars[-1].time + interval,
                }
            )
    interval = RESOLUTIONS[request.settings.timeframe]
    first = (request.start + interval - 1) // interval * interval
    end = request.end // interval * interval
    test = [c for c in candles if first <= c.time < end]
    expected = (end - first) // interval
    if (
        not test
        or len(test) != expected
        or test[0].time != first
        or test[-1].time + interval != end
    ):
        raise DeltaError(
            "Historical data is incomplete for the selected period; no bars were filled"
        )
    if request.settings.requires_higher_history():
        hinterval = RESOLUTIONS[request.settings.higher_timeframe]
        if not higher or higher[-1].time + hinterval != request.end // hinterval * hinterval:
            raise DeltaError("Higher-timeframe history is incomplete for the selected period")
    return {
        "status": "passed",
        "expected_candles": expected,
        "actual_candles": len(test),
        "coverage_percent": 100.0,
        "data_sha256": digest.hexdigest(),
        "code_sha256": CODE_SHA256,
        "datasets": datasets,
        "scope": "Complete, ordered, UTC-aligned OHLCV; no synthetic or forward-filled bars. "
        "This checks structure, not the exchange's underlying tick accuracy.",
    }
