# Free local strategy research

Open **Backtest** and choose a **Test type**. All four modes use the same replay engine, ATR levels, contract metadata, fees, partial exits, and stop progression. They make unauthenticated historical-data reads and never start the paper/demo runner or save its settings.

## Test modes

| Mode                    | Inputs                                                       | Result                                                                                                 |
| ----------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Single backtest         | One market and strategy                                      | Complete trade ledger, equity curve, risk metrics, monthly returns, and signal checks                  |
| Compare coins           | Up to 12 comma-separated perpetual symbols                   | Per-market results and errors; successful markets remain inspectable when another market lacks history |
| Compare parameters      | One or two UI axes with comma-separated numeric values       | Per-combination results, in-sample ranking, heatmap, and individual ledgers                            |
| Walk-forward validation | Parameter grid, initial training percentage, test fold count | Earlier-data selection, subsequent untouched test folds, and a combined out-of-sample equity curve     |

The API permits up to four grid axes. Supported keys: `fast_ema`, `slow_ema`, `cmo_length`, `cmo_threshold`, `atr_length`, `macro_sma`, `sl_atr`, `tp0`, `tp1`, `tp2`. Each axis accepts one to eight unique values; a study is limited to 24 combinations and 96 walk-forward training runs. Test periods remain limited to 366 days.

Comparison rankings use return, daily Sharpe, daily Sortino, or Calmar. A minimum closed-trade count is editable. Undefined metrics, too few trades, or failed signal checks exclude a run from ranking; its results remain visible. Invalid settings are listed separately. A winning in-sample combination is not evidence of future profitability.

Coin comparisons run independent starting-capital accounts. They do not form a shared-capital portfolio. Identical contract counts can represent different exposures because Delta contract values differ. Recently listed, inactive, unsupported, or incomplete-history markets show individual errors.

## Walk-forward methodology

The initial training percentage defines the first earlier-data window. The remaining candles are divided into consecutive, non-overlapping test folds. For every fold:

1. Evaluate each valid candidate using the expanding training history ending **at the test start**.
2. Rank eligible candidates using training metrics only. Test results never select that fold's settings.
3. Start the selected candidate flat in the next test window. If no candidate is eligible, hold cash.
4. Close remaining exposure at the fold end and carry ending capital into the next fold.

The combined result includes **test folds only**. The initial training period is excluded. The realized-loss budget restarts per fold; forced fold-boundary closes include fees. If test capital is exhausted, later folds are not executed and the report states this. Training/test boundaries, selected parameters, training trials, and test summaries are included in study JSON.

## Data cache and provenance

`.runtime/history.sqlite3` stores validated, closed OHLCV candles. Keys include source name, upstream host, symbol, resolution, and candle timestamp. Public and demo candles cannot satisfy one another's requests. Product metadata is fetched again for each market.

- **Reuse saved candles:** validate cached rows, fetch missing intervals, and store complete batches.
- **Download fresh candles:** refetch the requested ranges and replace validated batches.
- **Bypass cache:** use the provider directly without reading or updating the cache.

There are no synthetic gap fills or silently shortened results. A full-period request fails if history or warmup is unavailable. Validated earlier batches may remain cached after a later request fails or is cancelled. Provider corrections require a fresh download; cache entries do not automatically expire.

Methodology and JSON include source, timeframe, cached/downloaded counts, and fetch-time bounds. Compressed research results and exported reports are stored under `.runtime/research/<run-id>/`. Only the current process's latest run is accessible through the UI/API; old files remain local for manual archival or removal. Neither cache nor reports are committed to Git.

## Risk metrics and exports

Daily returns are calculated from **UTC closing equity**, with a **365-day crypto year** and a zero risk-free rate. Partial first/last days appear in the data but are excluded from daily risk ratios. At least two complete days are required for annualized metrics. Undefined ratios appear as dashes, not infinity. Monthly returns compound the available daily returns; an asterisk marks a partial month.

Trade win rate and profit factor continue to use the closed-trade ledger. Daily Sharpe, Sortino, volatility, and optional QuantStats statistics use a return series; they do not replace trade win rate. Drawdown duration uses candle-close observations and includes recovery time.

**HTML report** works with the base installation and embeds its chart and styles. **JSON results** preserves the full selected curve/ledger plus study metadata. Install the optional upstream QuantStats report integration with:

```bash
uv sync --frozen --group research
uv run --frozen --group research delta-bot
```

QuantStats export uses complete UTC daily returns, `periods_per_year=365`, and no benchmark ticker or market-data download. Its button is available when installed and the selected run has at least two complete days and non-flat returns. Short or flat series can still use the native HTML report. Third-party metrics may use different definitions; the report identifies daily statistics separately.

## Sampled signal consistency

Choose 16, 32, or 64 checkpoints, or disable the check explicitly. The checker also samples entry-signal times, up to the chosen count. It compares full-history prepared signals with new strategy instances receiving the runner's last 600 closed signal candles and only closed higher-timeframe candles.

A mismatch can indicate future-data dependence or history-window differences. Failed/incomplete checks exclude a configuration from research ranking. **Passing samples does not prove every signal is unbiased.** A custom strategy without `prepare()` receives a limited result: its streaming inputs are bounded, but there is no independent prepared path to compare. This is our implementation of the checking method; it does not run Freqtrade's CLI.

Backtrader reference checks remain 20 controlled broker scenarios; they are not an independent replay of the selected strategy, study grid, or full year. For studies, reference checks run on the initially selected detailed result; other rows retain their replay analytics and signal-check results.

## HTTP interface

`POST /api/backtests` accepts the existing request plus optional fields:

```json
{
  "cache": "use",
  "check_lookahead": true,
  "lookahead_samples": 16,
  "research": {
    "kind": "walk_forward",
    "grid": { "fast_ema": [7, 9, 12], "sl_atr": [1.5, 2.0] },
    "objective": "return",
    "minimum_trades": 1,
    "train_percent": 60,
    "folds": 3
  }
}
```

Include normal `settings`, `source`, `start`, `end`, capital, fee, and slippage fields as before. Other `research.kind` values are `single`, `multi_coin` (with `symbols`), and `parameters` (with `grid`).

- `GET /api/backtests`: current job, run ID, selected result, and study rows.
- `POST /api/backtests/cancel` with `{}`: cancel research after the current request; trading is unaffected.
- `GET /api/backtests/results/{index}?run_id=...`: a completed row's full result.
- `GET /api/backtests/reports/{index}?run_id=...&format=html`: offline HTML attachment.
- Use `format=quantstats` for the optional upstream report.

Walk-forward row `0` is the combined test result; rows `1..N` are individual test folds. A stale run ID is rejected so an old UI response cannot select a new run's results.

## Sources and validation

The [awesome-systematic-trading catalogue](https://github.com/paperswithbacktest/awesome-systematic-trading) informed the selection of methods. Walk-forward and caching approaches are described by [PyBroker](https://github.com/edtechre/pybroker); signal-bias checking is described by [Freqtrade](https://www.freqtrade.io/en/stable/lookahead-analysis/); optional reports use [QuantStats](https://github.com/ranaroussi/quantstats), distributed under Apache 2.0.

The core research/cache/check/report code is implemented in this project. PyBroker, Freqtrade, and VectorBT are not runtime dependencies. The hosted Papers With Backtest service, paid datasets, and paid strategy unlocks are not used.

Regression tests cover cache isolation/gaps/refresh, future-dependent signal detection, training-only selection, capital carry, empty training eligibility, cancellation, report escaping, route restrictions, and local QuantStats export. CI runs the base suite on Python 3.12–3.14 and optional research checks on Python 3.12. Historical probes and automated checks are separate from live demo execution; funding, taxes, liquidation and order-book liquidity remain excluded.
