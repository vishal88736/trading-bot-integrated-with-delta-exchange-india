"""Return-series analytics and offline reports; trade statistics stay in the ledger."""

import calendar
import html
import math
import os
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from statistics import mean, stdev


def analytics(result):
    initial = result["summary"]["initial_balance"]
    start, end = result["actual_start"], result["actual_end"]
    closing = {}
    peak, peak_time, longest = initial, start, 0
    underwater = False
    for point in result["equity_curve"]:
        closing[datetime.fromtimestamp(point["time"] - 1, UTC).date()] = point["equity"]
        if point["equity"] >= peak:
            if underwater:
                longest = max(longest, point["time"] - peak_time)
            peak, peak_time = point["equity"], point["time"]
            underwater = False
        else:
            longest = max(longest, point["time"] - peak_time)
            underwater = True
    daily, months, previous = [], defaultdict(list), initial
    for day, equity in sorted(closing.items()):
        timestamp = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
        value = equity / previous - 1 if previous > 0 else None
        item = {
            "date": day.isoformat(),
            "time": timestamp + 86400,
            "equity": equity,
            "return": value,
            "complete": timestamp >= start and timestamp + 86400 <= end,
        }
        daily.append(item)
        months[day.strftime("%Y-%m")].append(item)
        previous = equity
    returns = [d["return"] for d in daily if d["complete"] and d["return"] is not None]
    sharpe = sortino = volatility = cagr = calmar = None
    if len(returns) >= 2:
        deviation = stdev(returns)
        downside = math.sqrt(mean(min(r, 0.0) ** 2 for r in returns))
        sharpe = mean(returns) / deviation * math.sqrt(365) if deviation > 1e-15 else None
        sortino = mean(returns) / downside * math.sqrt(365) if downside > 1e-15 else None
        volatility = deviation * math.sqrt(365) * 100
        ending = result["summary"]["ending_equity"]
        if ending > 0:
            try:
                cagr = math.expm1(math.log(ending / initial) * 365 * 86400 / (end - start)) * 100
            except OverflowError:
                cagr = None
        drawdown = result["summary"]["max_drawdown_percent"]
        calmar = cagr / drawdown if drawdown > 0 and cagr is not None else None
    monthly = []
    for month, items in sorted(months.items()):
        year, number = map(int, month.split("-"))
        first = int(datetime(year, number, 1, tzinfo=UTC).timestamp())
        last = first + calendar.monthrange(year, number)[1] * 86400
        values = [d["return"] for d in items]
        monthly.append(
            {
                "month": month,
                "return_percent": (math.prod(1 + r for r in values) - 1) * 100
                if all(r is not None for r in values)
                else None,
                "partial": first < start or last > end,
            }
        )
    metrics = {
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "cagr_percent": cagr,
        "annual_volatility_percent": volatility,
        "max_drawdown_days": longest / 86400,
        "complete_days": len(returns),
        "best_day_percent": max(returns) * 100 if returns else None,
        "worst_day_percent": min(returns) * 100 if returns else None,
    }
    metrics = {
        key: value if value is None or math.isfinite(value) else None
        for key, value in metrics.items()
    }
    try:
        quantstats_version = version("quantstats")
    except PackageNotFoundError:
        quantstats_version = None
    return {
        "metrics": metrics,
        "daily_returns": daily,
        "monthly_returns": monthly,
        "quantstats_version": quantstats_version,
        "methodology": [
            "UTC daily equity returns; 365-day crypto year; zero risk-free rate.",
            "Sharpe uses sample standard deviation; Sortino uses all-day downside deviation.",
            "Partial UTC days are displayed but excluded from daily risk ratios.",
            "Annualized metrics need two complete days; undefined ratios are blank.",
            "Trade win rate and profit factor use closed trades, separately from daily returns.",
            "Monthly cells marked partial cover only the available part of that month.",
        ],
    }


def formatted(value, suffix=""):
    return "—" if value is None else f"{value:,.2f}{suffix}"


def html_report(result, study=None):
    """A self-contained report with no scripts, remote images, or paid service."""
    escape = html.escape
    data = result.get("analytics") or analytics(result)
    symbol, quote = result["settings"]["symbol"], result["quote"]
    summary = result["summary"]
    metrics = [
        ("Net P&L", formatted(summary["net_pnl"], " " + quote)),
        ("Return", formatted(summary["return_percent"], "%")),
        ("Maximum drawdown", formatted(summary["max_drawdown_percent"], "%")),
        ("Closed trades", str(summary["trades"])),
        ("Trade win rate", formatted(summary["win_rate"], "%")),
        ("Daily Sharpe", formatted(data["metrics"]["sharpe"])),
        ("Daily Sortino", formatted(data["metrics"]["sortino"])),
        ("Calmar", formatted(data["metrics"]["calmar"])),
        ("Longest drawdown", formatted(data["metrics"]["max_drawdown_days"], " days")),
        ("Fees", formatted(summary["fees"], " " + quote)),
    ]
    cards = "".join(
        f"<div><span>{escape(k)}</span><strong>{escape(v)}</strong></div>" for k, v in metrics
    )
    points = result["equity_curve"]
    low, high = min(p["equity"] for p in points), max(p["equity"] for p in points)
    width = high - low or 1
    stride = max(1, len(points) // 1000)
    sampled = sorted(set(range(0, len(points), stride)) | {len(points) - 1})
    coordinates = " ".join(
        f"{20 + i / max(1, len(points) - 1) * 960:.2f},"
        f"{240 - (points[i]['equity'] - low) / width * 210:.2f}"
        for i in sampled
    )
    monthly = "".join(
        f"<tr><td>{escape(row['month'])}{' *' if row['partial'] else ''}</td>"
        f"<td>{formatted(row['return_percent'], '%')}</td></tr>"
        for row in data["monthly_returns"]
    )
    assumptions = "".join(
        f"<li>{escape(text)}</li>" for text in result["assumptions"] + data["methodology"]
    )
    bias = result.get("lookahead_check", {})
    validation = escape(bias.get("message", "Lookahead check was not run"))
    study_section = ""
    if study:
        rows = "".join(
            "<tr>"
            + "".join(
                f"<td>{escape(str(v))}</td>"
                for v in [
                    row.get("label", ""),
                    row.get("status", ""),
                    formatted((row.get("summary") or {}).get("return_percent"), "%"),
                    row.get("error") or "",
                ]
            )
            + "</tr>"
            for row in study.get("rows", [])
        )
        study_section = (
            f"<h2>{escape(study.get('title', 'Study'))}</h2>"
            f"<p>{escape(study.get('methodology', ''))}</p>"
            f"<table><tr><th>Run</th><th>Status</th><th>Return</th><th>Note</th></tr>{rows}</table>"
        )
    period = " → ".join(
        datetime.fromtimestamp(t, UTC).isoformat()
        for t in [result["actual_start"], result["actual_end"]]
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(symbol)} backtest report</title><style>
body{{font:16px/1.6 system-ui,sans-serif;color:#21332b;background:#f7f8f5;margin:0}}
main{{max-width:1100px;margin:auto;padding:32px}}h1{{font-size:32px}}h2{{margin-top:32px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}}
.metrics div,svg{{background:white;border:1px solid #dce3dc;border-radius:12px;padding:16px}}
strong,span{{display:block}}strong{{font-size:23px}}svg{{width:100%;box-sizing:border-box}}
table{{width:100%;border-collapse:collapse;background:white}}td,th{{text-align:left;padding:12px;
border-bottom:1px solid #dce3dc}}p,li{{max-width:90ch}}@media print{{body{{background:white}}}}
</style></head><body><main><h1>{escape(symbol)} · Backtest report</h1>
<p>{escape(result["source"])}<br>{escape(period)}</p><div class="metrics">{cards}</div>
<h2>Equity after fees</h2><svg viewBox="0 0 1000 270" role="img" aria-label="Equity curve">
<polyline points="{coordinates}" fill="none" stroke="#267451" stroke-width="2"/></svg>
<h2>Monthly returns</h2><p>* Partial month</p>
<table><tr><th>UTC month</th><th>Return</th></tr>{monthly}</table>{study_section}
<h2>Validation</h2><p>{validation}</p><h2>Methodology</h2><ul>{assumptions}</ul>
<p>Historical simulation. Funding, liquidation and live execution are not modeled.</p>
</main></body></html>"""


def quantstats_report(result, path):
    """Optional upstream report, using only local returns and no ticker downloads."""
    try:
        os.environ.setdefault("MPLCONFIGDIR", str(path.parent / "matplotlib"))
        import matplotlib

        matplotlib.use("Agg")
        import pandas as pd
        import quantstats as qs
    except ImportError:
        from clients.delta import DeltaError

        raise DeltaError("Install research dependencies: uv sync --group research") from None
    daily = (result.get("analytics") or analytics(result))["daily_returns"]
    complete = [d for d in daily if d["complete"] and d["return"] is not None]
    if len(complete) < 2 or not any(d["return"] for d in complete):
        from clients.delta import DeltaError

        raise DeltaError("QuantStats needs at least two complete days and non-flat returns")
    series = pd.Series(
        [d["return"] for d in complete], index=pd.to_datetime([d["date"] for d in complete])
    )
    try:
        with matplotlib.rc_context(
            {
                "font.family": "DejaVu Sans",
                "font.sans-serif": ["DejaVu Sans"],
                "svg.fonttype": "path",
            }
        ):
            qs.reports.html(
                series,
                benchmark=None,
                rf=0,
                periods_per_year=365,
                title=f"{result['settings']['symbol']} · UTC daily returns",
                output=str(path),
                download_filename=str(path),
                compounded=True,
            )
    except Exception:
        from clients.delta import DeltaError

        path.unlink(missing_ok=True)
        raise DeltaError(
            "QuantStats could not render this return series; use the offline HTML report"
        ) from None
