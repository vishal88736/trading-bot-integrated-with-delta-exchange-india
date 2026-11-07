"""Optional statistics and execution checks against the user-selected repositories.

No source is vendored. Only pinned, unmodified local checkouts are loaded. The
statistics readers consume our exported fills/equity. Backtrader separately
executes controlled bracket scenarios using its own broker.
"""

import importlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

REFERENCES = (
    (
        "PyBacktestPro",
        "https://github.com/raviwijerathna1/PyBacktestPro",
        "cf276f47ea664a91b1579d41a0ca5e5a59a8239e",
    ),
    (
        "trading-strategy-backtesting-suite",
        "https://github.com/Trading-Backtesting/trading-strategy-backtesting-suite",
        "ceaceb1858d22de9a51c0e19f568961cc4195160",
    ),
    (
        "Backtrader",
        "https://github.com/mementum/backtrader",
        "b853d7c90b6721476eb5a5ea3135224e33db1f14",
    ),
)
CHECK_LOCK = threading.Lock()


def verify_checkout(path, commit):
    actual = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"], text=True
    )
    if actual != commit or dirty:
        raise ValueError("Reference must be at its reviewed commit with no tracked modifications")


def compare(actual, expected):
    return {
        key: {
            "reference": value,
            "dashboard": expected.get(key),
            "passed": (value is None and expected.get(key) is None)
            or (
                value is not None
                and expected.get(key) is not None
                and math.isclose(float(value), float(expected[key]), rel_tol=1e-7, abs_tol=1e-7)
            ),
        }
        for key, value in actual.items()
    }


def validate(result, root, only=None):
    """Run optional third-party readers away from the trading server's process."""
    if only is not None and (not only or set(only) - {name for name, _, _ in REFERENCES}):
        raise ValueError("Choose a known reference")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("DELTA_")}
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(root.resolve()), *(only or [])],
            input=json.dumps(result),
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
            check=True,
        )
        return json.loads(process.stdout)
    except (subprocess.SubprocessError, ValueError):
        return [
            {
                "name": name,
                "url": url,
                "commit": commit,
                "status": "error",
                "message": "Optional reference worker could not complete",
            }
            for name, url, commit in REFERENCES
            if only is None or name in only
        ]


def _validate(result, root, only=None):
    records = []
    for name, url, commit in REFERENCES:
        if only is not None and name not in only:
            continue
        record = {
            "name": name,
            "url": url,
            "commit": commit,
            "kind": "execution_scenarios" if name == "Backtrader" else "statistics",
            "scope": (
                "Controlled bracket execution scenarios; not a replay of this strategy or period"
                if name == "Backtrader"
                else "Statistics from the same trade ledger; not independent strategy execution"
            ),
        }
        path = root / name
        if not path.exists():
            record.update(
                status="unavailable", message="Optional reference checkout is not installed"
            )
            records.append(record)
            continue
        try:
            verify_checkout(path, commit)
            if name == "Backtrader":
                from bot.backtrader_checks import check_scenarios

                record.update(check_scenarios(path))
                records.append(record)
                continue
            import numpy as np
            import pandas as pd

            with CHECK_LOCK:
                points = [
                    {"time": result["actual_start"], "equity": result["summary"]["initial_balance"]}
                ] + result["equity_curve"]
                dates = pd.to_datetime([p["time"] for p in points], unit="s", utc=True)
                equity = pd.Series([p["equity"] for p in points], index=dates)
                summary = result["summary"]
                if name == "PyBacktestPro":
                    cache = root / ".matplotlib"
                    cache.mkdir(exist_ok=True, parents=True)
                    os.environ.setdefault("MPLCONFIGDIR", str(cache.resolve()))
                    module_name = "_delta_reference_pybacktestpro"
                    module = sys.modules.get(module_name)
                    if module is None:
                        spec = importlib.util.spec_from_file_location(
                            module_name, path / "engine.py"
                        )
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)
                    trades = [
                        types.SimpleNamespace(
                            pnl=t["net_pnl"],
                            pnl_pct=t["net_pnl"] / (t["entry"] * t["quantity"]),
                            side="LONG" if t["side"] == "buy" else "SHORT",
                            bars_held=1,
                            commission=t["fees"],
                        )
                        for t in result["trades"]
                    ]
                    wrapper = types.SimpleNamespace(equity_curve=equity, trades=trades)
                    dd = module.DrawDownAnalyzer().analyze(wrapper)
                    stats = module.TradeAnalyzer().analyze(wrapper)
                    checks = compare(
                        {
                            "max_drawdown_percent": -float(dd["max_drawdown_pct"]),
                            "trades": stats["total"],
                            "win_rate": stats.get("win_rate"),
                            "net_pnl": stats.get("pnl", {}).get("total", 0.0),
                            "fees": stats.get("commission", {}).get("total", 0.0),
                        },
                        summary,
                    )
                else:
                    # Load only the suite's metrics package. Its plotting module needs
                    # JS assets absent from that repository and is not part of this check.
                    module_name = "_delta_reference_suite"
                    if module_name not in sys.modules:
                        package = types.ModuleType(module_name)
                        package.__path__ = [str(path / "engine")]
                        sys.modules[module_name] = package
                    module = importlib.import_module(module_name + "._stats")
                    rows = []
                    for t in result["trades"]:
                        entry_time = pd.to_datetime(t["entry_time"], unit="s", utc=True)
                        exit_time = pd.to_datetime(t["exit_time"], unit="s", utc=True)
                        rows.append(
                            {
                                "Size": t["quantity"],
                                "PnL": t["net_pnl"],
                                "ReturnPct": t["net_pnl"] / (t["entry"] * t["quantity"]),
                                "EntryTime": entry_time,
                                "ExitTime": exit_time,
                                "EntryBar": max(0, dates.searchsorted(entry_time) - 1),
                                "ExitBar": min(len(dates) - 1, dates.searchsorted(exit_time)),
                                "Duration": exit_time - entry_time,
                            }
                        )
                    frame = pd.DataFrame(
                        rows,
                        columns=[
                            "Size",
                            "PnL",
                            "ReturnPct",
                            "EntryTime",
                            "ExitTime",
                            "EntryBar",
                            "ExitBar",
                            "Duration",
                        ],
                    )
                    if frame.empty:
                        frame = frame.astype(
                            {"PnL": float, "ReturnPct": float, "EntryBar": int, "ExitBar": int}
                        )
                        frame["Duration"] = pd.to_timedelta(frame["Duration"])
                    # Benchmark price is irrelevant to the metrics compared here.
                    ohlc = pd.DataFrame(
                        {"Close": np.linspace(100.0, 101.0, len(equity))}, index=dates
                    )
                    stats = module.compute_stats(frame, equity.to_numpy(), ohlc, None)
                    win_rate = float(stats["Win Rate [%]"])
                    checks = compare(
                        {
                            "ending_equity": float(stats["Equity Final [$]"]),
                            "return_percent": float(stats["Return [%]"]),
                            "max_drawdown_percent": -float(stats["Max. Drawdown [%]"]),
                            "trades": int(stats["# Trades"]),
                            "win_rate": win_rate if math.isfinite(win_rate) else None,
                        },
                        summary,
                    )
                record.update(
                    status="passed" if all(c["passed"] for c in checks.values()) else "mismatch",
                    checks=checks,
                )
        except ImportError:
            record.update(
                status="unavailable",
                message="Install the optional research dependencies: uv sync --group research",
            )
        except Exception as exc:
            record.update(
                status="error", message=f"Reference check could not complete ({type(exc).__name__})"
            )
        records.append(record)
    return records


if __name__ == "__main__":
    print(
        json.dumps(
            _validate(json.load(sys.stdin), Path(sys.argv[1]), only=sys.argv[2:] or None),
            allow_nan=False,
        )
    )
