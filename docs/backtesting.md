# Backtesting and reproducibility

All computation runs locally. Public Delta OHLCV, the persistent candle cache,
the built-in simulator and the optional reference engines require no paid data
subscription. Exchange data availability can limit a market's usable date range.

## Data and candle timing

The selected public/demo source supplies operational linear-perpetual product
metadata and OHLCV. Signal and higher-timeframe candles are fetched separately,
including 600 warmup candles per needed timeframe. The cache separates source
host, market, resolution and opening timestamp. No other exchange's data is
silently substituted.

Both loader and replay enforce complete UTC-aligned, ordered, non-duplicated
candles. Missing bars, incomplete requested coverage, malformed prices and
unclosed candles stop the run. No forward filling, interpolation or synthetic
market bars are used. Partial date boundaries are rounded inward to whole bars.
The coverage check verifies structure, not the exchange's underlying tick data.
Zero-volume counts include warmup and are reported; enabled breakout volume
confirmation cannot pass with absent/zero reference volume.

Inputs are identified by SHA-256 over source, market, resolutions, contract units,
tick size, quote asset and every OHLCV value, including warmup. A separate code
fingerprint covers Python files in `bot`, `strategies` and `clients` when loaded.
The JSON export contains the exact settings and request. Cache fetch timestamps
record when those candles were obtained, not when the exchange last revised them.

Decisions use closed candles; higher-timeframe availability uses closing times.
Entries and confirmed strategy exits execute at the next signal-candle open.
The four additional strategies and their exact rules are in [strategies.md](strategies.md).
Sampled entry/exit consistency checks compare prepared indicators with fresh
rolling windows. Sampling is useful regression evidence, not proof of no bias.

## Fills, costs and exposure

- One position per simulated market; integer Delta contracts and actual contract
  value convert price differences into quote-asset P&L.
- Initial stop takes priority when an OHLC bar also touches targets. After TP1,
  the stop moves to rounded entry; after TP2 it moves to TP1. If that advanced stop
  is also inside the bar, it closes the remainder before another target.
- A gap through the stop fills at the worse open. Target touches use the target
  reference price with adverse execution costs. Native exits use the next open.
- All fills incur the configured taker fee. There are no resting maker targets in
  the runner. Slippage plus half the configured bid–ask spread is adverse on both
  entries and exits. Combined impact must fit the entry execution limit.
- Fixed contracts or risk-percent sizing apply margin, fees, notional/contract
  caps and realized-loss limits. Risk sizing rounds down and skips positions
  that cannot support at least four contracts. Gaps can exceed planned risk.
- Remaining positions close at the last complete bar's close. Drawdown is sampled
  at candle closes, rather than being an intrabar mark-to-market maximum.

Each position records reference/fill prices and separate commissions, slippage and
spread costs. Before-cost P&L minus those costs reconciles to net P&L. This removes
costs from the same fills; a zero-cost rerun could produce different ATR levels,
entries and sizes. Profit factor uses net closed-position results, including every
partial exit. Undefined ratios are displayed as missing, not infinity or zero.
Daily Sharpe/Sortino use complete UTC days and 365-day annualization.

The cost sensitivity table reruns frozen selected settings on the exact same data.
Only slippage changes; fees and spread stay fixed. Scenarios above the execution
limit are explicitly skipped. Parameter/multi-coin studies validate the selected
row; other rows retain their own ledgers and input exports. Walk-forward sensitivity
and broker checks use the selected test-fold rules, flat fold boundaries and their
own carried capital; they do not redo training selection using future results.

Funding, taxes, liquidation, depth-dependent slippage, queue position, partial
exchange fills, variable spread and actual stop-amendment latency are outside this
simulation. Candle volume is not treated as proof of executable exit liquidity.
Small trade samples are labelled in the UI. Neither 100 trades nor a profit factor
above 1.5 alone establishes profitability or robustness across market regimes.

## Optional independent checks

`PyBacktestPro` and the trading-strategy suite recompute statistics from this
engine's ledger. Backtrader runs 20 separate controlled execution scenarios.
Backtesting.py replays the complete selected period from raw OHLCV using its
unmodified broker with a project execution adapter. That adapter independently
constructs rounded levels, partial quantities and risk sizing, while the broker
accepts orders, charges fees, reduces positions and accounts for equity. Contract
prices are scaled by contract value so one broker unit equals one Delta contract.
Signals are shared with the primary engine. This does not independently verify
strategy mathematics or reconstruct the unknown tick order inside candles.
Bankruptcy differences are reported as not comparable, never as a successful check.

Pinned external checkouts are kept under ignored `.runtime/references`; source is
not bundled. Missing optional dependencies/checkouts show as unavailable.

```bash
uv sync --frozen --group research
uv run --frozen --group research python scripts/setup_references.py
uv run --frozen --group research delta-bot
```

After completion, download **JSON results** and **Replay inputs**, then reproduce
the optional checks offline using the same code revision and reference checkouts:

```bash
uv run --frozen --group research python scripts/check_backtest_references.py \
  /path/to/backtest.json --inputs /path/to/delta-backtest-0-inputs.json.gz
```

The worker gets no `DELTA_*` environment variables and makes no trading requests.
Exact inputs include public candles and contract metadata; credentials and account
balances are not exported. Full ledgers remain in compressed local research
artifacts so changing result rows never substitutes the selected row's data.
