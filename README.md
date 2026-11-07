# Trading Bot Integrated with Delta Exchange India

A local trading dashboard for **Delta India demo accounts**, with account funds and holdings, configurable EMA/CMO/ATR entries, a stop loss that advances after each target, and free backtests covering up to one year. The layout follows the supplied light automation-dashboard reference with larger text, stronger contrast, and readable forms and tables.

## Run locally

Requires Python 3.12–3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen
uv run delta-bot
```

Open **http://127.0.0.1:8000**. The app binds to loopback only. A normal Python alternative is `python -m venv .venv`, activate that environment, then `python -m pip install -r requirements.txt` and `python strategy_runner.py`; use the uv lockfile for reproducible versions.

1. Start a **paper run** to view public demo market data without credentials. Paper fills are simulated at the observed ticker price.
2. Open **Settings → Connection** and enter keys from [Delta's demo account](https://demo.delta.exchange/). Keys must have the required account/trading permissions and your IP must match Delta's API-key settings.
3. Set **Strategy → Execution mode → demo**, choose the market/timeframes and risk limits, save, then select **Start demo run**. Starting requires an explicit UI confirmation.

Production trading is not available. Account reads and all trading requests use `https://cdn-ind.testnet.deltaex.org`. Paper and demo share the public demo market feed. The separate public-history client can read unauthenticated product metadata and candles from `https://api.india.delta.exchange` for backtesting; it rejects authenticated requests and writes.

## Account funds and holdings

Open **Account** after saving demo credentials in **Connection settings**. Account data refreshes every 15 seconds independently of the trading runner; no trading run is needed to fetch your balances.

- **Funds:** wallet balance, available trading balance and blocked margin in the selected asset. Available funds are taken from Delta's `available_balance`, rather than inferred by subtracting margin from cash.
- **Wallet holdings:** every returned asset with isolated, cross and portfolio margin columns. Currencies are kept separate; there is no invented USD conversion or combined account total.
- **Positions:** all demo account products with direction, quantity, entry/mark prices, margin, exchange-reported unrealized P&L, liquidation price and margin mode.
- **Orders and fills:** open/pending orders across the account (cursor pagination up to 1000, with a truncation notice) and the latest 50 exchange fills. The bot's paper ledger stays separate from the exchange account.
- Each section reports its fetch time. Read errors retain the last successful values and mark them stale; disconnected or unavailable balances show a dash. Missing margin/P&L fields are not replaced with zeros. Margined positions can lag the exchange by up to 10 seconds, as documented by Delta.

## Free backtesting, up to one year

Open **Backtest** and choose a date range or the **1 year** preset. Select either **Delta India public market** history (default) or **Delta demo** history. Both use free public candle endpoints with no API key or paid data dependency. Account credentials are never sent to either reference repository, and backtesting never submits exchange orders.

Choose market, signal/higher timeframes, strategy and dates on the setup card. Open **Strategy settings** for indicator parameters, risk/targets and trading costs. These controls are independent of saved runner settings and can be changed while the runner is active. Set initial quote capital, then select **Run backtest**. Results are organized into **Overview**, **Trades**, and **Methodology** tabs; **View trade** opens its exit and stop-update timeline. A full year is supported even on the 1-minute timeframe; data is fetched in windows within Delta's 2000-candle API limit. The application refuses missing or gapped history instead of reporting a shorter period as a full-year test.

Results include net P&L, return, candle-close drawdown, closed trades, win rate, profit factor, fees, an equity curve, rejected entries, individual partial exits, and stop advances. The JSON download includes the full equity curve, parameters, source and contract tick size. No trades is a valid result. The final allocation closes at the end of the test.

Signals use closed candles and enter on the next candle open with slippage. The historical engine shares rounded trade levels, allocation and stop-ladder code with the demo runner. Indicator calculation is prepared once for long runs and matches the live runner's rolling 600-candle window. If both stop and target are touched within one candle, the stop wins. After a partial target the advanced stop can also trigger within that candle. This conservative ordering is reported explicitly.

Funding, tax, liquidation, order-book liquidity and intrabar price ordering are not modeled. Historical target touches differ from the demo runner's polling behavior. The realized-loss limit also applies during replay; increase it deliberately in the test form if you want the strategy to keep taking entries after that simulated loss threshold.

### Checking results with your two reference repositories

The optional checks use the actual statistics implementations from [PyBacktestPro](https://github.com/raviwijerathna1/PyBacktestPro) and [trading-strategy-backtesting-suite](https://github.com/Trading-Backtesting/trading-strategy-backtesting-suite). They recalculate drawdown, trade count and win rate; PyBacktestPro also checks ledger P&L and fees, while the suite checks final equity and return. They consume our trade ledger/equity, so **agreement is a statistics check, not an independent replay of strategy orders or proof of fill realism**. Their profit-factor definitions differ, so that field is not claimed as comparable.

```bash
uv sync --frozen --group research
uv run --frozen --group research python scripts/setup_references.py
uv run --frozen --group research delta-bot
```

The setup helper downloads reviewed, pinned commits under ignored `.runtime/references/`. There are no subscription or paid service dependencies. The UI reports checks as unavailable if optional sources/dependencies are absent; it does not claim they passed. To recheck an exported report:

```bash
uv run --frozen --group research python scripts/check_backtest_references.py /path/to/backtest.json
```

Reviewed commits: PyBacktestPro `cf276f47ea664a91b1579d41a0ca5e5a59a8239e`, suite `ceaceb1858d22de9a51c0e19f568961cc4195160`. The first repository has no license file; the suite contains components with differing upstream licenses. Their source is not vendored or redistributed in this project. Checks run in a separate process with `DELTA_*` environment variables removed.

## Your stop-loss ladder

| Event | Partial exit | New stop on the remaining position |
| --- | --- | --- |
| Entry | — | Entry ∓ 2 × ATR by default |
| TP1 | Floor of 50% of original contracts | Entry price |
| TP2 | Floor of 25% of original contracts | TP1 price |
| TP3 | All remaining contracts | Position closes |

The same ladder applies in reverse for shorts. Targets default to 1×, 2×, and 4× entry ATR and are editable in **Risk & targets**. With a 2×ATR initial stop these are **0.5R, 1R, and 2R**, respectively. At least four contracts are required to support all three exits. For quantities not divisible by four, the final tier receives the remainder. Levels are rounded to the exchange tick size.

The stop never moves backward. In demo mode an entry carries a native exchange stop; after a confirmed partial exit the app edits that existing stop and checks the returned price. A stop at entry does not cover fees, slippage, gaps, or funding.

Targets are checked at the configured polling interval, then executed as reduce-only market orders. A price briefly touching a target between polls can be missed. Pausing the runner **keeps the native demo stop in place**, but pauses target monitoring. The final target closes the runner allocation; a Chandelier trail is not part of this version.

## Strategy settings

Default: BTCUSD, 5-minute signal candles, 1-hour trend filter, EMA 9/21, CMO 14, Wilder ATR 14, higher-timeframe SMA 200, and 1× demo leverage. These are starting parameters, not a performance recommendation. Demo leverage is editable from 1× to 50× and is explicitly set before entry; the bot does not inherit the exchange's default leverage.

- Long: closed price above fast EMA above slow EMA; CMO crosses upward through the configured threshold; fully closed higher-timeframe price/EMAs agree; optional higher-timeframe SMA filter agrees.
- Short: the mirrored conditions, crossing downward through the negative threshold.
- One position at a time. Signals use only closed candles; forming higher-timeframe candles are excluded. Entries occur on the next poll after a fresh candle close, using the current market price; exact exchange candle-open fills cannot be guaranteed.
- ATR and target distances are frozen at entry. No pyramiding or automatic reversal entries.

This is an **independent implementation of the supplied mathematical rules**, not a verified reproduction of UAlgo's proprietary indicator. Regression channels, alternative RSI rules, and structural swing overrides were not specified precisely and are not silently approximated.

For a different entry algorithm, edit [strategies/custom_strategy.py](strategies/custom_strategy.py) and select `custom_strategy` in Settings. Return `Signal("buy" or "sell", atr_value, last_closed_candle.time, "reason")`, or `None`. The runner owns sizing, exits, the stop ladder, and restart handling.

## Runtime and recovery

- Settings, credentials, state and recent activity live under ignored `.runtime/`. Credential/state files are written atomically with owner-only file permissions on Linux. Credentials are stored locally in plaintext, not encrypted; the status API never returns them. Environment keys in `.env` are supported, with saved UI credentials taking precedence.
- Pause before changing runner settings; active or unresolved trades prevent changes. Demo credentials can be saved while paper mode runs, so account reads work independently. Changing credentials used for demo execution requires a paused runner and resolved demo positions. Reuse the same runtime directory when restarting an active demo trade.
- Every exchange write records a pending intent before transmission. Ambiguous timeouts, incomplete fills, unconfirmed stop edits, or account drift pause execution; writes are never retried automatically.
- For an unresolved demo trade, inspect/close it and cancel remaining product orders in Delta's demo UI. **Reconcile flat account** verifies the selected product is flat with no open orders before clearing local recovery state. It does not place or cancel orders. In paper mode reconciliation discards the simulated position.
- Quote-notional and contract limits block new entries. The realized-loss circuit breaker uses known bot fills since the runtime was created; it excludes funding, manual trades and unobserved native-stop fills. The displayed P&L is a local estimate, not the account balance or a complete risk ledger. After an external/native stop the app halts for reconciliation instead of inventing a fill price.
- Only operational vanilla linear perpetuals are supported. Unsupported contracts, stale prices, candle gaps and missing native protection halt the runner.
- Keep one server per runtime folder; a process lock prevents competing runners. The local API checks browser origin and host and does not expose a production URL override.

## Validation

```bash
uv run --frozen pytest
node --check bot/static/app.js
node --check bot/static/research.js
npm ci --ignore-scripts
npm test
uv build --no-sources
```

Tests cover account parsing/stale data/credential redaction, historical pagination, replay fills/costs/risk limits, long/short target ladders, rolling-window indicator parity, restart recovery, ambiguous writes, signing and local API controls. DOM tests exercise navigation, account currency separation, independent backtest settings, one-year presets and large equity curves. GitHub Actions tests Python 3.12, 3.13 and 3.14, plus UI DOM behavior on Node 26, without credentials or exchange orders.

Public market reads and a full-year BTCUSD five-minute replay (105,120 test candles, 365 days) were verified during implementation, with both reference statistics checks passing. A seven-day demo-data replay was also checked. These are completed historical simulations, not proof of profitability or demo execution. No demo account credentials were available, so live authenticated balances, demo orders and stop amendments remain unverified. Browser visual QA was unavailable; DOM/API checks do not establish visual rendering.

## Upstream and modernization

Based on [delta-exchange/trading-bots](https://github.com/delta-exchange/trading-bots), upstream commit `9676a2686b2c463c3c66cb001544ec417963ef96` (2019-05-01). Its Git history is retained through the merge and the original HMAC signing primitive is adapted in `clients/delta.py`.

The 2019 market maker, random quote generation, automatic margin top-ups, tracked account-JSON workflow, PM2 setup, Raven, v1 REST client and legacy WebSockets were replaced with the demo REST v2 runner, configurable strategy, local web UI and locked modern Python dependencies. REST polling intentionally avoids deprecated socket channels/authentication. No claim is made that the old unhedged market-maker behavior is preserved.

API behavior was checked against [Delta's official API documentation](https://docs.delta.exchange/) and [official Python REST client](https://github.com/delta-exchange/python-rest-client). Package versions were checked on PyPI on 2026-11-07; exact transitive versions are in `uv.lock`.

The upstream repository has no LICENSE file at the imported revision. Attribution is retained; this repository does not grant additional rights to the upstream code. The original sample's caution remains applicable: understand its limitations and use demo testing before considering real trading.
