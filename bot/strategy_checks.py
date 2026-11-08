"""Sample prepared signals against the same closed-candle inputs used by the runner."""

import bisect
import math

from bot.models import RESOLUTIONS
from bot.research import Cancelled
from strategies.catalogue import strategy_type


def lookahead_check(request, candles, higher, result, progress=None, factory=None):
    make = factory or strategy_type(request.settings.strategy)
    strategy = make(request.settings)
    if not hasattr(strategy, "prepare"):
        return {
            "status": "limited",
            "samples": 0,
            "mismatches": [],
            "message": "Streaming strategy receives closed candles; no prepared path to compare.",
            "scope": "A full prepared-signal audit requires a strategy with prepare().",
        }
    try:
        prepared = strategy.prepare(candles, higher)
        indices = [
            i
            for i, c in enumerate(candles)
            if request.start <= c.time
            and c.time + RESOLUTIONS[request.settings.timeframe] <= request.end
        ]
        count = min(request.lookahead_samples, len(indices))
        chosen = {indices[round(i * (len(indices) - 1) / max(count - 1, 1))] for i in range(count)}
        signal_times = {t["signal_time"] for t in result["trades"][: request.lookahead_samples]}
        chosen.update(i for i in indices if candles[i].time in signal_times)
        htimes = [c.time + RESOLUTIONS[request.settings.higher_timeframe] for c in higher]
        mismatches = []
        signals = 0
        for index in sorted(chosen):
            if progress:
                progress(f"Checking closed-candle consistency: {len(chosen)} checkpoints")
            boundary = candles[index].time + RESOLUTIONS[request.settings.timeframe]
            end = bisect.bisect_right(htimes, boundary)
            reference = prepared.at(index)
            streamed = make(request.settings).evaluate(
                candles[max(0, index - 599) : index + 1], higher[max(0, end - 600) : end]
            )
            signals += reference is not None or streamed is not None
            same = reference is None and streamed is None
            if reference is not None and streamed is not None:
                same = (
                    reference.side == streamed.side
                    and reference.time == streamed.time
                    and math.isclose(reference.atr, streamed.atr, rel_tol=1e-8, abs_tol=1e-8)
                )
            if hasattr(prepared, "exit_at"):
                fresh = make(request.settings)
                lower = candles[max(0, index - 599) : index + 1]
                upper = higher[max(0, end - 600) : end]
                for side in ("buy", "sell"):
                    same = same and (
                        prepared.exit_at(index, side) == fresh.exit_reason(side, lower, upper)
                    )
            if not same:
                mismatches.append({"time": candles[index].time})
        return {
            "status": "failed" if mismatches else "passed",
            "samples": len(chosen),
            "signal_samples": signals,
            "mismatches": mismatches,
            "message": f"{len(mismatches)} mismatches across {len(chosen)} sampled candle closes.",
            "scope": (
                "Full prepared history versus fresh 600-candle streaming windows and closed "
                "higher-timeframe candles. Mismatches can indicate lookahead or window dependence; "
                "passing samples does not prove every signal is unbiased."
            ),
        }
    except Cancelled:
        raise
    except Exception:
        return {
            "status": "error",
            "samples": 0,
            "mismatches": [],
            "message": "Signal consistency check could not complete; inspect the custom strategy.",
            "scope": "An incomplete check is not a pass.",
        }
