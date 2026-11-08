# Strategy catalogue

Choose a strategy in **Strategy settings** or in the independent **Backtest** form. Each strategy has editable parameters and appears in single tests, multi-coin comparisons, parameter comparisons, and walk-forward validation. New strategy selections are not saved or started automatically.

**Load strategy preset** changes the open form only. Presets suggest 4h/1d for breakout and EMA trend, 15m/4h for SMC, and 1h/4h for RSI. Change the timeframes and filters to suit your research. Presets preserve the selected execution mode, market, direction policy, and sizing choices.

## Shared execution

- Only closed signal candles and already-closed higher-timeframe candles can inform a decision.
- Replay entries fill at the next candle open. The running bot acts at the first fresh poll following a close; it does not guarantee the exact next opening price.
- The ATR stop/target ladder remains **TP1 → entry, TP2 → TP1, TP3 → close**, with exchange tick rounding and integer partial allocations.
- New strategies default to **Strategy or ladder** exits: an enabled strategy exit can close the remaining position before the final target. Select **Ladder only** to use ATR exits exclusively.
- In replay, strategy exits are scheduled at the next opening price after their confirming close. Stop/target processing applies during the preceding candle. In the runner, price-based stop/target handling precedes the fresh-close strategy check.
- **Trade direction** supports both directions, long only, or short only.

Existing EMA/CMO and custom-entry defaults retain their original behavior. The newly added default settings preserve existing saved-position signatures. Changes to an active trade's strategy/settings still require that trade to be resolved first.

## Momentum breakout

Identifier: `momentum_breakout`.

Long entry requires a close above the highest high of the **prior** N candles plus the configured ATR buffer. Short entry requires a close below the lowest prior low minus the buffer. The decision candle is excluded from that range.

When enabled, current volume must be at least the configured multiple of the **prior** volume average. A zero multiplier disables the volume filter explicitly. Missing/zero historical volume cannot satisfy an enabled positive-volume filter.

Optional higher-timeframe confirmation requires the closed higher-timeframe price above fast EMA above slow EMA for longs, or the inverse for shorts.

Strategy exit: long closes below the prior range low, short closes above the prior range high.

Defaults: range 20, volume average 20, volume multiplier 1.5, ATR buffer 0, higher-timeframe EMA 50/200.

## EMA trend following

Identifier: `ema_trend`.

Long entry: fast EMA crosses above slow EMA, and price closes above fast EMA. Short entry: fast crosses below slow, with price below fast. Optional higher-timeframe confirmation uses the same directional price/EMA alignment.

Strategy exit: the fast EMA is below slow for an existing long, or above slow for an existing short. This is a regime exit; it does not require catching the first opposing crossover after a paused period.

Defaults: EMA 50/200, higher-timeframe confirmation enabled.

For daily signal candles, disable higher-timeframe confirmation; the current API-supported timeframe list has no interval above 1d. Higher-timeframe history is not downloaded when disabled for these strategies.

## RSI mean reversion

Identifier: `rsi_reversion`.

Wilder RSI has two editable entry modes:

- **Recovery:** long when RSI crosses back above oversold while remaining below the exit level; short when it crosses back below overbought while remaining above the exit level. A jump beyond the mean is not a recovery entry.
- **Extreme cross:** long when RSI crosses into oversold; short when it crosses into overbought.

An optional range filter requires the absolute fast/slow EMA gap to be no greater than the configured ATR multiple. This is an explicit price-based trend-strength proxy. Optional higher-timeframe confirmation can restrict reversions to the direction of a broader trend.

Strategy exit: RSI reaches or exceeds the exit level for a long, or reaches/falls below it for a short.

Defaults: RSI 14, thresholds 30/70, exit 50, recovery entry, range filter enabled with maximum EMA gap 2 ATR, EMA 50/200.

## SMC price action

Identifier: `smc_price_action`. These rules detect price patterns in OHLC candles; they do **not** establish that institutions placed orders, and do not use wallet flows or order-book data.

1. Confirm a break of structure: a bullish close above the prior swing-range high, or bearish close below its low.
2. Require displacement: the candle body must cover at least the configured fraction of its high-low range.
3. Form a zone:
   - **Order block:** the full range of the most recent opposite-color candle within the configured search window, identified when the structure break closes.
   - **Fair value gap:** a bullish three-candle gap when current low is above the high two bars earlier, or a bearish gap when current high is below the low two bars earlier. It must form on the BOS candle or within the following two candles and meet the minimum gap size.
   - **Either:** accept either zone type.
4. Wait for a **subsequent** candle to touch the zone and reject it: a bullish candle closing above its upper edge, or bearish candle closing below its lower edge.
5. Apply direction and optional higher-timeframe confirmation at the rejection close.

A zone cannot generate an entry on the candle that creates it. A close through its far edge invalidates it; stale zones expire. Only the latest 16 active zones are retained. A confirmed rejection consumes that zone and its linked setup; repeated structure breaks do not re-arm an already-used order block. Rejections filtered out by direction/macro confirmation also consume the setup.

Strategy exit: an opposing close through the prior swing range. The hard stop and targets remain ATR-based rather than being moved automatically to the zone boundaries.

Defaults: prior swing 20, order-block search 20, lifetime 60, FVG zone, body/range at least 0.6, minimum gap 0 bps.

## Planned-risk sizing

**Fixed contracts** remains the default. To enable adaptive sizing, select **Risk percent** and choose 0.1–2% planned risk. The default percentage is 1%.

The budget uses:

- Backtests: current simulated cash; the initial cash comes from the backtest capital field.
- Paper runner: configured paper starting capital plus this bot's saved realized P&L. This is a simulation estimate, separate from the connected demo wallet.
- Demo runner: a fresh authenticated wallet read in the matching quote/settlement asset. The lower of wallet balance and available funds is used. Missing/ambiguous balances or different settlement units block sizing.

For each whole contract, the estimate reserves the rounded initial stop distance, an extra tick, adverse entry/exit execution using the configured maximum entry slippage, and estimated fees. The size is rounded **down** and capped by maximum contracts, quote notional, and available margin/entry fees at the selected leverage.

The three-part ladder requires at least four whole contracts. If four cannot fit, the trade is skipped; the bot never rounds upward to force a trade. Partial quantities use half, quarter, and the integer remainder.

Planned stop risk is not a guaranteed maximum loss. Gaps, funding, actual exchange fees, liquidation, and execution beyond the reserve can change the result. Native demo fills/stops still require separate live validation; implementation tests use mock receipts and historical simulation.

## Research and evidence

Parameter selectors offer fields relevant to the selected strategy and filters. The API rejects grids containing inactive strategy parameters. Inputs, actual quantities, sizing estimates, indicator settings, costs, and exits are recorded in reports/JSON.

Prepared and streaming strategy paths use the same 600-candle history window. Sampled consistency checks compare both **entry and strategy-exit decisions** with fresh rolling windows. Automated tests cover deterministic long/short signals, absent volume, closed higher-timeframe availability, zone formation/retests/invalidation/expiry, duplicate order-block consumption, RSI values, 600-candle parity, next-open exits, sizing caps, and legacy recovery.

These strategy families were requested using [CoinQuant's comparison](https://www.coinquant.ai/blog/best-crypto-trading-strategy-in-2026-backtested-and-ranked), [ZebPay's overview](https://zebpay.com/in/blog/advance-trading-crypto-strategies-in-2026), [Audacity's descriptions](https://audacity.capital/trading-guides/most-profitable-trading-strategies/), and [AvaTrade's overview](https://www.avatrade.com/education/online-trading-strategies/crypto-trading-strategies).

CoinQuant's quoted figures describe its own January 2021–August 2026 Binance BTCUSDT **spot**, daily, long-only, unleveraged, fully invested tests with 0.1% taker fees. They are publisher-reported results, not reproduced results for this project. Our selectable filters, Delta futures contract sizing, timeframes, three-tier ATR exits, and one-year replay limit define a different experiment. The app reports its actual simulated results and does not label a strategy the guaranteed or universal best performer.
