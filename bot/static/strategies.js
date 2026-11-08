/* Editable strategy catalogue. Presets modify the form only. */
const STRATEGY_NAMES = {
  trend_signals: "EMA / CMO trend signals",
  momentum_breakout: "Momentum breakout",
  ema_trend: "EMA trend following",
  smc_price_action: "SMC price action",
  rsi_reversion: "RSI mean reversion",
  custom_strategy: "Custom strategy",
};
const STRATEGY_DEFAULTS = {
  trade_direction: "both",
  htf_filter: "enabled",
  exit_mode: "strategy_or_ladder",
  trend_fast_period: 50,
  trend_slow_period: 200,
  breakout_lookback: 20,
  breakout_volume_length: 20,
  breakout_volume_multiplier: 1.5,
  breakout_buffer_atr: 0,
  rsi_length: 14,
  rsi_oversold: 30,
  rsi_overbought: 70,
  rsi_exit_level: 50,
  rsi_entry_mode: "recovery",
  rsi_range_filter: "enabled",
  rsi_max_ema_gap_atr: 2,
  smc_swing_length: 20,
  smc_order_block_lookback: 20,
  smc_zone_expiry: 60,
  smc_zone_type: "fvg",
  smc_body_ratio: 0.6,
  smc_min_gap_bps: 0,
  sizing_mode: "fixed_contracts",
  risk_per_trade_percent: 1,
  paper_capital_quote: 10000,
};
const EXTRA_STRATEGY_FIELDS = [
  [
    "strategy",
    "trade_direction",
    "Trade direction",
    ["both", "long_only", "short_only"],
  ],
  [
    "strategy",
    "htf_filter",
    "Higher-timeframe confirmation",
    ["enabled", "disabled"],
  ],
  ["strategy", "trend_fast_period", "Trend fast EMA", "number", 2, 200],
  ["strategy", "trend_slow_period", "Trend slow EMA", "number", 3, 500],
  ["strategy", "breakout_lookback", "Prior range (candles)", "number", 2, 200],
  [
    "strategy",
    "breakout_volume_length",
    "Prior volume average (candles)",
    "number",
    2,
    200,
  ],
  [
    "strategy",
    "breakout_volume_multiplier",
    "Minimum volume multiplier (0 = off)",
    "number",
    0,
    20,
    0.1,
  ],
  [
    "strategy",
    "breakout_buffer_atr",
    "Breakout buffer (× ATR)",
    "number",
    0,
    5,
    0.1,
  ],
  ["strategy", "rsi_length", "RSI length", "number", 2, 200],
  ["strategy", "rsi_oversold", "RSI oversold", "number", 1, 49.9, 0.1],
  ["strategy", "rsi_overbought", "RSI overbought", "number", 50.1, 99, 0.1],
  ["strategy", "rsi_exit_level", "RSI exit level", "number", 1, 99, 0.1],
  [
    "strategy",
    "rsi_entry_mode",
    "RSI entry trigger",
    ["recovery", "extreme_cross"],
  ],
  ["strategy", "rsi_range_filter", "RSI range filter", ["enabled", "disabled"]],
  [
    "strategy",
    "rsi_max_ema_gap_atr",
    "Maximum EMA gap (× ATR)",
    "number",
    0.1,
    20,
    0.1,
  ],
  [
    "strategy",
    "smc_swing_length",
    "Structure range (prior candles)",
    "number",
    2,
    100,
  ],
  [
    "strategy",
    "smc_order_block_lookback",
    "Order-block search (candles)",
    "number",
    2,
    100,
  ],
  ["strategy", "smc_zone_expiry", "Zone lifetime (candles)", "number", 2, 200],
  [
    "strategy",
    "smc_zone_type",
    "Retest zone",
    ["fvg", "order_block", "either"],
  ],
  [
    "strategy",
    "smc_body_ratio",
    "Minimum BOS candle body / range",
    "number",
    0.1,
    1,
    0.05,
  ],
  [
    "strategy",
    "smc_min_gap_bps",
    "Minimum FVG size (bps)",
    "number",
    0,
    1000,
    0.1,
  ],
  ["risk", "exit_mode", "Exit rules", ["strategy_or_ladder", "ladder_only"]],
  [
    "risk",
    "sizing_mode",
    "Position sizing",
    ["fixed_contracts", "risk_percent"],
  ],
  [
    "risk",
    "risk_per_trade_percent",
    "Planned risk per trade (%)",
    "number",
    0.1,
    2,
    0.1,
  ],
  [
    "risk",
    "paper_capital_quote",
    "Paper starting capital (quote)",
    "number",
    1,
    1000000000,
    0.01,
  ],
];
const STRATEGY_DESCRIPTIONS = {
  trend_signals:
    "EMA cloud, CMO zero/threshold cross, and closed higher-timeframe trend. ATR targets and the stop ladder manage exits.",
  momentum_breakout:
    "Close beyond the prior range with a configurable volume filter. Strategy exits close on an opposite range break.",
  ema_trend:
    "Fast/slow EMA crossover confirmed by price. Strategy exits close on an opposing EMA regime.",
  smc_price_action:
    "Confirmed structure break and displacement, then a later FVG or order-block rejection. These are OHLC price-action rules; they do not identify institutional orders.",
  rsi_reversion:
    "RSI recovery from an extreme, or an extreme crossing, with an optional EMA-gap range filter. Strategy exits close at the RSI exit level.",
  custom_strategy:
    "Your Python evaluate() entry rules, with the shared ATR stop ladder and risk controls.",
};
function normalizeStrategySettings(settings) {
  return { ...STRATEGY_DEFAULTS, ...settings };
}
function isLegacyStrategy(name) {
  return ["trend_signals", "custom_strategy"].includes(name);
}
function updateStrategyFields(prefix = "setting-") {
  const selector = $(prefix + "strategy");
  if (!selector) return;
  const name = selector.value,
    legacy = isLegacyStrategy(name);
  const backtest = prefix === "backtest-setting-";
  const busy = backtest && (backtestRunning || backtestSubmitting);
  const risk = $(prefix + "sizing_mode")?.value === "risk_percent";
  for (const [, key] of fields) {
    const input = $(prefix + key);
    if (!input) continue;
    let visible = true;
    if (
      [
        "fast_ema",
        "slow_ema",
        "cmo_length",
        "cmo_threshold",
        "macro_sma",
      ].includes(key)
    )
      visible = legacy;
    if (
      [
        "htf_filter",
        "trend_fast_period",
        "trend_slow_period",
        "exit_mode",
      ].includes(key)
    )
      visible = !legacy;
    if (["trend_fast_period", "trend_slow_period"].includes(key))
      visible =
        !legacy &&
        (name === "ema_trend" ||
          $(prefix + "htf_filter").value === "enabled" ||
          (name === "rsi_reversion" &&
            $(prefix + "rsi_range_filter").value === "enabled"));
    if (key.startsWith("breakout_")) visible = name === "momentum_breakout";
    if (key.startsWith("rsi_")) visible = name === "rsi_reversion";
    if (key.startsWith("smc_")) visible = name === "smc_price_action";
    if (key === "smc_order_block_lookback")
      visible =
        name === "smc_price_action" &&
        $(prefix + "smc_zone_type").value !== "fvg";
    if (key === "smc_min_gap_bps")
      visible =
        name === "smc_price_action" &&
        $(prefix + "smc_zone_type").value !== "order_block";
    if (key === "rsi_max_ema_gap_atr")
      visible =
        name === "rsi_reversion" &&
        $(prefix + "rsi_range_filter").value === "enabled";
    if (key === "risk_per_trade_percent") visible = risk;
    if (key === "paper_capital_quote")
      visible = risk && !backtest && $("setting-mode").value === "paper";
    if (key === "contracts") visible = !risk;
    input.parentElement.classList.toggle("hidden", !visible);
    input.disabled = busy || !visible;
  }
  const higher = $(prefix + "higher_timeframe");
  const needsHigher = legacy || $(prefix + "htf_filter").value === "enabled";
  higher.disabled = busy || !needsHigher;
  higher.parentElement.classList.toggle("inactive-field", !needsHigher);
  const description = $(
    backtest ? "backtest-strategy-description" : "strategy-description",
  );
  if (description) description.textContent = STRATEGY_DESCRIPTIONS[name] || "";
}
function applyStrategyPreset(prefix = "setting-") {
  const name = $(prefix + "strategy").value;
  const updates = { ...STRATEGY_DEFAULTS };
  for (const key of [
    "sizing_mode",
    "risk_per_trade_percent",
    "paper_capital_quote",
    "trade_direction",
  ])
    delete updates[key];
  // Explicit button press changes fields; it never saves or starts a runner.
  if (!isLegacyStrategy(name)) {
    updates.timeframe =
      name === "smc_price_action"
        ? "15m"
        : name === "rsi_reversion"
          ? "1h"
          : "4h";
    updates.higher_timeframe =
      name === "smc_price_action"
        ? "4h"
        : name === "rsi_reversion"
          ? "4h"
          : "1d";
  }
  for (const [key, value] of Object.entries(updates)) {
    const input = $(prefix + key);
    if (input) input.value = value;
  }
  updateStrategyFields(prefix);
  if (prefix === "backtest-setting-") updateBacktestSummary();
  else updateRiskPreview("setting-", "ratio-note");
  toast(
    "Preset loaded into this form. Review your settings before saving or testing.",
  );
}
function renderStrategyFlow(s) {
  const labels = {
    trend_signals: [
      "EMA cloud",
      s.fast_ema + " / " + s.slow_ema,
      "Momentum",
      "CMO " + s.cmo_length + " · " + s.cmo_threshold + " cross",
    ],
    custom_strategy: [
      "Custom strategy",
      "Python entry rules",
      "Confirmation",
      "Your evaluate() rules",
    ],
    momentum_breakout: [
      "Breakout",
      "Prior " + s.breakout_lookback + "-bar range",
      "Volume",
      s.breakout_volume_multiplier
        ? s.breakout_volume_multiplier + "× prior mean"
        : "Filter off",
    ],
    ema_trend: [
      "EMA trend",
      s.trend_fast_period + " / " + s.trend_slow_period,
      "Confirmation",
      "Closed crossover",
    ],
    smc_price_action: [
      "Structure break",
      s.smc_swing_length + " prior bars",
      "Retest zone",
      s.smc_zone_type.replaceAll("_", " "),
    ],
    rsi_reversion: [
      "RSI reversion",
      s.rsi_length + " · " + s.rsi_entry_mode,
      "Range filter",
      s.rsi_range_filter === "enabled"
        ? "EMA gap ≤ " + s.rsi_max_ema_gap_atr + " ATR"
        : "Filter off",
    ],
  }[s.strategy];
  $("flow-trend-title").textContent = labels[0];
  $("flow-ema").textContent = labels[1];
  $("flow-momentum-title").textContent = labels[2];
  $("flow-cmo").textContent = labels[3];
  if (!isLegacyStrategy(s.strategy))
    $("flow-macro").textContent =
      s.htf_filter === "enabled"
        ? s.higher_timeframe +
          " · EMA " +
          s.trend_fast_period +
          " / " +
          s.trend_slow_period
        : "Filter off";
  if (s.sizing_mode === "risk_percent")
    $("flow-size").textContent = s.risk_per_trade_percent + "% planned risk";
}
document.addEventListener("DOMContentLoaded", () => {
  for (const prefix of ["setting-", "backtest-setting-"]) {
    for (const key of [
      "strategy",
      "htf_filter",
      "sizing_mode",
      "mode",
      "smc_zone_type",
      "rsi_range_filter",
    ])
      $(prefix + key)?.addEventListener("change", () => {
        updateStrategyFields(prefix);
        if (prefix === "backtest-setting-") updateBacktestSummary();
        else updateRiskPreview("setting-", "ratio-note");
      });
    const button = $(
      prefix === "setting-" ? "strategy-preset" : "backtest-strategy-preset",
    );
    if (button) button.onclick = () => applyStrategyPreset(prefix);
    updateStrategyFields(prefix);
  }
});
