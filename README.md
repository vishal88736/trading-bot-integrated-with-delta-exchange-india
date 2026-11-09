# Trading Bot Integrated with Delta Exchange India

[![Checks](https://github.com/vishal88736/trading-bot-integrated-with-delta-exchange-india/actions/workflows/checks.yml/badge.svg?branch=main)](https://github.com/vishal88736/trading-bot-integrated-with-delta-exchange-india/actions/workflows/checks.yml)

A local trading workspace for **Delta Exchange India demo accounts**. Configure your strategy, inspect account funds and positions, and run free historical backtests covering up to one year.

The bot takes partial profits and advances the remaining stop loss: **TP1 → entry, TP2 → TP1, TP3 → close**. Paper mode is the default. Production trading is not implemented.

[Quick start](#quick-start) · [Account setup](#connect-your-demo-account) · [Backtesting](#free-backtesting) · [Strategy](#strategy-and-stop-loss-management) · [Development](#development-and-validation) · [Troubleshooting](#troubleshooting)

## Features

- **Automation dashboard:** candle chart, strategy flow, saved position, current stop, and activity history.
- **Reference-inspired UI:** charcoal cards, sidebar navigation, mint accents, gold coin artwork, volume/exit-allocation widgets, and responsive layouts across the workspace.
- **Configurable strategies:** EMA/CMO cloud, momentum breakout, EMA trend following, SMC price action, RSI mean reversion, or your own Python entry rules.
- **Sizing and exits:** optional planned-risk sizing (0.1–2%), direction controls, and strategy-specific exits alongside the ATR target/stop ladder.
- **Settings preview:** live target reward/risk and partial contract sizes, keyboard navigation, and field-level validation feedback.
- **Account information:** demo balances, available funds, margin, open positions, orders, and recent fills. Paper positions appear under Automation, while Account shows exchange data.
- **Free backtesting:** up to one year, validated candle coverage, caching, taker fees/slippage/spread, cost sensitivity, trade timelines, and offline reports.
- **Research:** multi-coin comparison, parameter heatmaps, expanding walk-forward validation, daily risk metrics and sampled signal consistency checks.
- **Reference checks:** two statistics readers, 20 Backtrader scenarios, and full-period Backtesting.py broker replay with a project execution adapter.

## Quick start

Install **Python 3.12–3.14**, **Git**, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Node.js is only needed for UI development checks; Python serves the dashboard directly.

```bash
git clone https://github.com/vishal88736/trading-bot-integrated-with-delta-exchange-india.git
cd trading-bot-integrated-with-delta-exchange-india
uv sync --frozen
uv run --frozen delta-bot
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**. No separate frontend server or JavaScript build is required.

Overview loads a **read-only Delta demo market preview while the runner is paused**. It uses public product, ticker and closed-candle reads with empty API credentials. Preview responses are cached for 15 seconds and the page refreshes them every 30 seconds; failed refreshes mark cached data stale. Trading stays under the existing Start/Pause controls. Account balances remain in **Funds & holdings** and keep their exchange source and freshness labels.

Choose **Area** or **Candles** above the chart. Hover, or focus the chart and use arrow keys, to inspect candle prices. **Ctrl K** (or **⌘ K**) searches workspace pages and settings. The mobile menu supports keyboard focus and Escape. The gold artwork is a local SVG; the UI needs no external image or font service.

The workspace fills the browser window. Backtest setup groups market/strategy and dates into separate sections; **Strategy settings** contains indicators, higher-timeframe confirmation, presets, risk and costs. Expand **Data & validation** for the history source, cache policy and consistency checks. Download actions appear after a completed result.

1. Open **Strategy settings** to choose the market, timeframes, indicators, and risk limits.
2. Keep execution mode on **paper**, save, and select **Start paper run** to simulate with demo market data. This mode needs no API credentials.
3. Open **Backtest** for historical testing, or **Account → Connection settings** to connect a demo account.

The selected page is retained in the URL: `#automation`, `#account`, or `#backtest`. A saved position shows as paused when its runner is stopped, with a **Resume** action.

Optional CLI settings:

```bash
uv run --frozen delta-bot --port 8001 --runtime .runtime
```

The server binds to `127.0.0.1` only. Reuse the same runtime directory to recover existing state; each runtime directory allows one server process.

<details>
<summary>Standard Python alternative</summary>

Create and activate a Python 3.12–3.14 virtual environment, then run:

```bash
python -m pip install -r requirements.txt
python strategy_runner.py
```

This installs the dependency ranges declared by the project. Use uv for the exact versions in `uv.lock`.

</details>

## Modes and supported markets

| Feature                 | Data source                        | Credentials         | Exchange orders            |
| ----------------------- | ---------------------------------- | ------------------- | -------------------------- |
| Paper runner            | Public Delta India demo feed       | None                | Simulated locally          |
| Demo runner             | Delta India demo account/feed      | Demo key and secret | Demo account only          |
| Account view            | Connected Delta India demo account | Demo key and secret | Read-only account requests |
| Public-history backtest | Delta India public candles         | None                | None                       |
| Demo-history backtest   | Delta India demo candles           | None                | None                       |

Account reads and demo execution use `https://cdn-ind.testnet.deltaex.org`. The public-history client reads `https://api.india.delta.exchange` and permits only unauthenticated product and candle requests.

The engine supports **currently operational vanilla linear perpetual futures**, such as `BTCUSD` and `ETHUSD`. The symbol must exist in your selected environment and have sufficient historical data. Spot, options, inactive contracts, and automatic multi-coin portfolio tests are outside the current engine.

## Connect your demo account

1. Create an API key in your [Delta India demo account](https://demo.delta.exchange/).
2. Configure the permissions required for wallet, position, order, and fill endpoints. Demo order execution requires Trading permission. Follow [Delta's current authentication documentation](https://docs.delta.exchange/#authentication).
3. Whitelist the **public outbound IP of the computer running the Python bot**. `127.0.0.1` is the local dashboard address, not the IP Delta sees. VPNs, ISP changes, or running the bot on another host can change that outbound IP.
4. Open **Connection settings**, enter the demo key and its matching secret, and select **Save demo connection**.
5. Select **Fetch account information** or open **Account** to check the connection.

Production keys do not work with the demo client. You can also use the `DELTA_API_KEY` and `DELTA_API_SECRET` environment variables shown in [.env.example](.env.example). Credentials saved through the UI take precedence.

To execute demo orders, choose **Strategy settings → Execution mode → demo**, save, and select **Start demo run**. Confirm the demo execution prompt. Pause the runner and resolve open or unresolved trades before changing its settings.

### Funds and holdings

The Account page loads independently of the trading runner. Balances, positions, orders, and fills use separate requests, so one slow or failed endpoint does not hold up the others.

| Section                       | Information                                                                                          |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| Funds                         | Wallet balance, exchange-reported available funds, and blocked margin in the selected asset          |
| Wallet holdings               | Assets and isolated, cross, and portfolio margin fields                                              |
| Open positions                | All account products, direction, contracts, entry, and available margin/P&L fields returned by Delta |
| Orders                        | Open and pending orders across products; up to 1,000 with a truncation notice                        |
| Recent fills                  | Latest 50 exchange fills                                                                             |
| Paper simulation (Automation) | Saved simulated position, entry, stop, and next target, including while paused                       |

Account reads refresh every 15 seconds. Each section shows its fetch time. Failed reads retain the last successful rows marked stale; missing values remain dashes. An unavailable empty snapshot is not presented as a flat account. Assets retain their own units rather than being added across currencies. Delta notes that margined positions can lag fills by up to 10 seconds. [Account API documentation](https://docs.delta.exchange/#get-margined-positions)

**Paper trades do not change demo exchange funds or holdings.** They appear in **Automation → Paper simulation**. **Account → Demo exchange positions** uses Delta account data. Saving API keys does not change the execution mode.

## Free backtesting

Open **[Backtest](http://127.0.0.1:8000/#backtest)** and:

1. Enter a market symbol and choose the entry strategy, signal timeframe, and higher timeframe.
2. Choose a date preset or custom dates. Dates use your local timezone; the maximum interval is 366 days.
3. Select **Delta India public market** or **Delta demo market** as the history source.
4. Set starting capital. Open **Strategy settings** for indicators, risk/targets, taker fees, slippage, spread, and cost sensitivity. Backtest settings are independent of the running bot.
5. Select **Run backtest**. The form shows starting/replay feedback and prevents duplicate submissions.

Choose **Test type** for a single replay, coin comparison, parameter comparison, or walk-forward validation. Research runs have progress and a separate **Cancel research** control. Their inputs never save or start the trading runner.

Results have **Overview**, **Trades**, and **Methodology** tabs. Open **View trade** for partial fills and stop updates. **JSON results** includes settings, ledger/equity, costs, data/code fingerprints, checks, and study metadata. **Replay inputs** downloads the exact OHLCV and contract metadata as compressed JSON, including selected test folds for walk-forward runs. **HTML report** is self-contained; optional **QuantStats** export uses local daily returns. See the [backtesting guide](docs/backtesting.md) for assumptions, reproduction, and validation scope.

See the [research guide](docs/research.md) for all modes, metrics, limits, and API examples.

The [strategy guide](docs/strategies.md) defines every new entry/exit rule, editable filter, preset, and risk-sizing assumption.

### Historical data

- The bot downloads OHLCV candles from Delta's public `GET /v2/history/candles` endpoint for your symbol, timeframe, and dates. These reads require no API key or paid data subscription. [API documentation](https://docs.delta.exchange/#get-historical-ohlc-candles), [API pricing FAQ](https://www.delta.exchange/algo/delta-exchange-apis)
- Requests use windows below the 2,000-candle response limit. Candles are sorted, deduplicated, and checked for continuous coverage.
- Signal and higher-timeframe history are fetched separately, with 600 earlier candles per timeframe for indicator warmup. Warmup is excluded from the reported trading period.
- Only closed candles are used. Missing history produces an error rather than invented prices or a silently shortened test.
- Closed candles are cached in `.runtime/history.sqlite3`, separated by source host, symbol, and timeframe. **Reuse saved candles** fills only missing ranges, **Download fresh candles** replaces the requested ranges, and **Bypass cache** downloads without using or updating the cache. Methodology records cached/downloaded counts and fetch times.

A 365-day test at five-minute resolution contains **105,120 test candles**. A full year is also supported at one-minute resolution, subject to data availability. Recently listed markets may need shorter periods.

### Simulation rules

Signals are evaluated at candle close; entries fill at the next candle open with adverse slippage. Only higher-timeframe candles already closed at the signal time are available to the strategy. Indicator calculation matches the runner's rolling 600-candle window.

The replay applies contract values, tick rounding, partial allocations, taker fees on every fill, adverse slippage, half the configured spread on each fill, position/notional limits, simulated funds, and the realized-loss limit. Targets also use taker fees because the runner sends market exits. Remaining positions close at the end. Zero trades is a valid result.

Cost attribution reconciles **before-cost P&L − fees − slippage − spread = net P&L** for these fills. The sensitivity table reruns the selected rules at 5/10/20 bps slippage by default, without downloading more candles or changing parameters. Scenarios above the configured execution limit are skipped. Walk-forward scenarios preserve the original training selections and carry their own capital between test folds.

OHLC candles do not reveal intrabar price order. The simulator gives the stop priority when both stop and target are touched. An advanced stop can close the remainder in the same candle as a partial target. Methodology reports this conservative policy. Funding, taxes, liquidation, order-book liquidity, and spread changes are not modeled. Historical fills differ from the runner's polled market exits.

### Optional validation checks

| Reference                                                                                                       | Checks                                                                                                      | Scope                                                           |
| --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| [PyBacktestPro](https://github.com/raviwijerathna1/PyBacktestPro)                                               | Drawdown, trades, win rate, ledger P&L, fees                                                                | Recalculates statistics from this engine's ledger/equity        |
| [Trading strategy backtesting suite](https://github.com/Trading-Backtesting/trading-strategy-backtesting-suite) | Ending equity, return, drawdown, trades, win rate                                                           | Recalculates statistics from this engine's ledger/equity        |
| [Backtrader](https://github.com/mementum/backtrader)                                                            | 20 long/short scenarios: partial exits, stop advances, gaps, costs, rounding, protective-order cancellation | Independently executes controlled OHLC paths with fixed signals |
| [Backtesting.py](https://github.com/kernc/backtesting.py) | Selected-period ledger, every equity sample, ending cash, fees, drawdown, risk sizing, native exits | Its broker handles orders and accounting; the project adapter implements Delta units and conservative OHLC exits. Strategy signals are shared. |

The statistics checks do not independently execute strategy orders. Backtrader uses its own unmodified simulated broker and independently constructs levels and allocations. Fault-injection tests verify detection of broken dashboard stop moves and partial sizes.

Backtrader's scenarios **do not replay your indicators or the full historical period**. Target scenarios use zero slippage to make limit-order fills comparable. Entry-candle exit activation, multiple targets/newly advanced stops in one candle, account risk-limit rules, and live exchange behavior are outside that comparison. Expand **Methodology → Validation checks → What this check covers** for details.

Backtesting.py replays raw inputs rather than consuming this engine's fills. It independently constructs rounded levels, allocations and risk quantities. It uses the reviewed upstream broker's order acceptance, commission, reductions and equity accounting. Its adapter defines same-candle event priority, gap handling and market-exit impact. It shares the strategy implementation and does not independently verify indicators or tick-level price paths. Bankrupt scenarios are reported as not comparable because the engines have different bankruptcy/liquidation semantics.

Install all four pinned references and the optional research dependencies:

```bash
uv sync --frozen --group research
uv run --frozen --group research python scripts/setup_references.py
uv run --frozen --group research delta-bot
```

Recheck an exported report:

```bash
uv run --frozen --group research python scripts/check_backtest_references.py /path/to/backtest.json --inputs /path/to/delta-backtest-0-inputs.json.gz
```

Run only Backtrader, without fetching market data or installing the statistics libraries:

```bash
uv run --frozen python scripts/setup_references.py --only Backtrader
uv run --frozen python scripts/check_backtest_references.py --only Backtrader
```

References live under ignored `.runtime/references/`, are checked against pinned commits, and run in a separate process with `DELTA_*` environment variables removed. Missing references are reported as unavailable. Keep `--group research` in uv commands when you want the statistics dependencies available.

## Strategy and stop-loss management

The built-in `trend_signals` strategy implements the supplied mathematical rules. It is an independent EMA/CMO/ATR implementation, not a verified reproduction of UAlgo's proprietary indicator.

| Setting                   | Default                 |
| ------------------------- | ----------------------- |
| Execution / market        | Paper / `BTCUSD`        |
| Signal / higher timeframe | `5m` / `1h`             |
| Fast / slow EMA           | 9 / 21                  |
| CMO / ATR periods         | 14 / 14                 |
| Higher-timeframe SMA      | 200; 0 disables it      |
| Initial stop              | 2 × entry ATR           |
| Targets                   | 1 ×, 2 ×, 4 × entry ATR |
| Contracts / leverage      | 4 / 1×                  |

**Long:** close above fast EMA above slow EMA; CMO crosses upward through its threshold; closed higher-timeframe price/EMAs and the optional SMA filter agree. **Short:** mirrored conditions. The runner holds one position at a time without pyramiding or automatic reversal.

| Event | Partial exit                       | Stop on remaining contracts                                       |
| ----- | ---------------------------------- | ----------------------------------------------------------------- |
| Entry | —                                  | Entry − 2 × ATR for longs; entry + 2 × ATR for shorts, by default |
| TP1   | Floor of 50% of original contracts | Entry price                                                       |
| TP2   | Floor of 25% of original contracts | TP1 price                                                         |
| TP3   | All remaining contracts            | Position closes                                                   |

At least four contracts are required. The final tier receives quantity remainders. Levels use the entry ATR and exchange tick size, including the breakeven stop. With the default stop, targets are **0.5R, 1R, and 2R**. Both settings dialogs preview reward/risk and partial quantities as you edit.

Demo entries include a native exchange stop. After a confirmed partial exit, the bot edits that stop and verifies its price. Targets are checked at the polling interval and executed with reduce-only market orders; brief touches between polls can be missed. Pausing keeps the existing native demo stop but pauses target monitoring. A stop at entry does not cover fees, slippage, gaps, or funding. TP3 closes the allocation; a Chandelier runner is not implemented.

### Your own strategy

Edit [strategies/custom_strategy.py](strategies/custom_strategy.py), implement `CustomStrategy.evaluate(candles, higher)`, and select **Custom strategy** in the UI.

- Inputs contain closed candles, oldest first.
- Return `None` when there is no entry.
- Return `Signal("buy" or "sell", positive_atr, candles[-1].time, "reason")` for an entry.
- The runner manages sizing, exits, stops, and recovery. The template produces no entries until you implement it.

See [the built-in strategy](strategies/trend_signals.py) and [signal model](bot/models.py) for the interface. Regression channels, alternate RSI rules, and structural swing overrides are not silently added.

## Runtime and recovery

Settings, credentials, and per-mode/per-symbol trade state live in ignored `.runtime/`. Credentials are plaintext local files created with owner-only permissions on Linux. Saved secret values are not returned by the status API. Keep `.env`, account keys, and runtime data out of Git.

- Pause before changing runner settings. Open/unresolved trades must be resolved before changing settings or demo credentials. Connecting account reads during a paper run is supported.
- Reuse the same runtime directory after a restart. Its process lock prevents competing dashboards.
- Ambiguous writes, incomplete fills, unconfirmed stop edits, account drift, stale prices, and candle gaps pause execution. Exchange writes are not automatically retried.
- To recover a demo trade, inspect and resolve its position and orders in Delta's demo UI. **Reconcile flat account** verifies that the selected product is flat with no open orders before clearing local recovery state; it does not place or cancel orders. In paper mode it discards the simulated position.
- The realized-loss limit covers known bot fills. It excludes funding, manual trades, and unobserved native-stop fills. Local estimated P&L is not an exchange balance.

## Troubleshooting

| Symptom                                       | What to check                                                                                     |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Automation shows a trade but Account is empty | Check paper/demo mode. Paper trades have their own panel; demo funds require a connected account. |
| `invalid_api_key`                             | Use an active demo key and its matching secret.                                                   |
| IP whitelist error                            | Check the bot host's current public outbound IP, including VPN/ISP changes.                       |
| Permission/signature error                    | Check Delta's endpoint permissions, matching key/secret, and automatic system time.               |
| Incomplete historical data                    | Try a later start, another supported market, or the other history source.                         |
| Few/no backtest trades                        | Check filters, dates, and Methodology's rejected entries, including the realized-loss limit.      |
| Reference unavailable                         | Run reference setup; include `--group research` for statistics checks.                            |
| Settings cannot save                          | Pause and resolve active trades. Validation opens the relevant tab and highlights the field.      |
| Dashboard cannot start                        | Check whether another instance owns the port or runtime lock before reusing its runtime.          |

## Development and validation

CI tests Python **3.12, 3.13, and 3.14**, and UI DOM behavior with **Node 26**.

```bash
uv sync --frozen
uv run --frozen python scripts/setup_references.py --only Backtrader
uv run --frozen pytest
npm ci --ignore-scripts
npm test
node --check bot/static/app.js
node --check bot/static/research.js
uv build --no-sources
```

Coverage includes replay fills/costs/risk limits, stop ladders, indicator-window parity, account parsing/staleness, secret redaction, restart recovery, ambiguous writes, API signing, local HTTP controls, Backtrader execution/fault detection, and UI interactions.

The [2026-11-09 validation record](docs/evidence/backtesting-validation.json) covers four one-year ETHUSD strategy replays (105,120 five-minute candles each), parameter comparison, walk-forward testing, risk sizing with spread, and ETHUSD/BTCUSD comparison. All four reference checks agreed on each selected run, with costs/ledgers reconciled and HTTP exports checked. Replay limits were raised to exercise execution paths; saved trading settings were preserved. These tested settings produced losses. This evidence supports implementation consistency, not a claim of profitable trading.

Public reads and full-year BTCUSD/ETHUSD five-minute simulations (105,120 candles for 365 days) have completed, along with seven-day demo-history tests and reference checks. These are historical simulations. Read-only authenticated account snapshots have also been checked locally. Actual demo orders and live stop amendments still require a dedicated demo validation run. DOM tests do not establish rendered-browser layout or live exchange execution.

### Project map

| Path                                                         | Purpose                                |
| ------------------------------------------------------------ | -------------------------------------- |
| [bot/static/](bot/static/)                                   | Dashboard HTML, CSS, and JavaScript    |
| [bot/web.py](bot/web.py)                                     | Local HTTP API                         |
| [bot/engine.py](bot/engine.py)                               | Runner and reconciliation              |
| [bot/account.py](bot/account.py)                             | Account snapshots                      |
| [bot/backtest.py](bot/backtest.py)                           | Historical replay and jobs             |
| [bot/risk.py](bot/risk.py)                                   | Levels, allocations, stop ladder       |
| [bot/reference_checks.py](bot/reference_checks.py)           | Reference workers and source pins      |
| [bot/market.py](bot/market.py)                               | Cached, read-only demo chart previews  |
| [bot/static/studio.css](bot/static/studio.css)               | Video-reference theme and layout       |
| [bot/static/studio.js](bot/static/studio.js)                 | Search, mobile navigation and widgets  |
| [bot/backtrader_checks.py](bot/backtrader_checks.py)         | Independent broker scenarios           |
| [strategies/](strategies/)                                   | Entry rules                            |
| [clients/delta.py](clients/delta.py)                         | Demo REST v2 client and public history |
| [tests/](tests/)                                             | Python and UI DOM checks               |
| [.github/workflows/checks.yml](.github/workflows/checks.yml) | CI matrix                              |

The [backend audit](docs/backend-audit.md) records the confirmed fixes and the limits of validation. The status API exposes execution provenance independently of account connectivity.

## Upstream and attribution

Based on [delta-exchange/trading-bots](https://github.com/delta-exchange/trading-bots) at commit `9676a2686b2c463c3c66cb001544ec417963ef96`, with its Git history retained. The original HMAC signing primitive is adapted in the REST client.

The legacy market maker, random quotes, automatic margin top-ups, tracked account JSON, PM2/Raven setup, v1 REST, and old WebSockets were replaced by this demo REST v2 dashboard. It uses REST polling and the versions in [uv.lock](uv.lock).

| Reference                          | Reviewed commit                            |
| ---------------------------------- | ------------------------------------------ |
| PyBacktestPro                      | `cf276f47ea664a91b1579d41a0ca5e5a59a8239e` |
| Trading strategy backtesting suite | `ceaceb1858d22de9a51c0e19f568961cc4195160` |
| Backtrader 1.9.78.123              | `b853d7c90b6721476eb5a5ea3135224e33db1f14` |
| Backtesting.py                     | `ca2e2611621e472542ba90f7243a1fa06a7d7108` |

Reference source is downloaded separately and is not bundled or redistributed here. Backtrader carries GPL-3.0 and Backtesting.py AGPL-3.0; the suite contains components with differing upstream licenses; PyBacktestPro has no license file at its reviewed revision. The imported Delta sample also has no LICENSE file at the imported revision. Attribution does not grant additional rights to those sources.

[Crypto-Back-Tester](https://github.com/shoaibghulam/Crypto-Back-Tester) was reviewed at `2e7e853371530c0ed368e12bd094aefd4bc7bfc4` for explicit costs, position sizing and frontend organization. Its README describes an MVP and its repository includes an MIT license. Its engine was not copied or installed as a second application; it is not an independent validator here.
