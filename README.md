# Trading Bot Integrated with Delta Exchange India

A local trading dashboard for **Delta India demo accounts**, with configurable EMA/CMO/ATR entries and a stop loss that advances after each target. The layout follows the supplied light automation-dashboard reference: market chart, strategy canvas, metrics, settings, and activity.

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

Production trading is not available. All exchange requests use `https://cdn-ind.testnet.deltaex.org`. Paper and demo share this public demo market feed; paper mode never sends exchange orders.

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
- Pause before changing settings. Active or unresolved trades prevent configuration and credential changes. Reuse the same runtime directory when restarting an active demo trade.
- Every exchange write records a pending intent before transmission. Ambiguous timeouts, incomplete fills, unconfirmed stop edits, or account drift pause execution; writes are never retried automatically.
- For an unresolved demo trade, inspect/close it and cancel remaining product orders in Delta's demo UI. **Reconcile flat account** verifies the selected product is flat with no open orders before clearing local recovery state. It does not place or cancel orders. In paper mode reconciliation discards the simulated position.
- Quote-notional and contract limits block new entries. The realized-loss circuit breaker uses known bot fills since the runtime was created; it excludes funding, manual trades and unobserved native-stop fills. The displayed P&L is a local estimate, not the account balance or a complete risk ledger. After an external/native stop the app halts for reconciliation instead of inventing a fill price.
- Only operational vanilla linear perpetuals are supported. Unsupported contracts, stale prices, candle gaps and missing native protection halt the runner.
- Keep one server per runtime folder; a process lock prevents competing runners. The local API checks browser origin and host and does not expose a production URL override.

## Validation

```bash
uv run --frozen pytest
node --check bot/static/app.js
uv build --no-sources
```

Tests cover long/short target ladders, restart recovery, ambiguous writes, configuration limits, request signing, demo-only execution, credentials and local API controls. GitHub Actions tests Python 3.12, 3.13 and 3.14 without credentials or network trading.

Public demo product, ticker and candle reads and a local paper-run API smoke test were verified during implementation. Authenticated demo orders and stop amendments require your demo account and have **not** been verified against the exchange. Browser visual QA was unavailable in the implementation session; API/static-asset checks do not establish visual rendering or profitability.

## Upstream and modernization

Based on [delta-exchange/trading-bots](https://github.com/delta-exchange/trading-bots), upstream commit `9676a2686b2c463c3c66cb001544ec417963ef96` (2019-05-01). Its Git history is retained through the merge and the original HMAC signing primitive is adapted in `clients/delta.py`.

The 2019 market maker, random quote generation, automatic margin top-ups, tracked account-JSON workflow, PM2 setup, Raven, v1 REST client and legacy WebSockets were replaced with the demo REST v2 runner, configurable strategy, local web UI and locked modern Python dependencies. REST polling intentionally avoids deprecated socket channels/authentication. No claim is made that the old unhedged market-maker behavior is preserved.

API behavior was checked against [Delta's official API documentation](https://docs.delta.exchange/) and [official Python REST client](https://github.com/delta-exchange/python-rest-client). Package versions were checked on PyPI on 2026-11-07; exact transitive versions are in `uv.lock`.

The upstream repository has no LICENSE file at the imported revision. Attribution is retained; this repository does not grant additional rights to the upstream code. The original sample's caution remains applicable: understand its limitations and use demo testing before considering real trading.
