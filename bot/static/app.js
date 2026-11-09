const $ = (id) => document.getElementById(id);
let current = null,
  polling = false,
  toastTimer;
const number = (value, digits = 2) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(undefined, {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.remove("show"), 4500);
}
async function api(path, body) {
  const response = await fetch(
    `/api/${path}`,
    body === undefined
      ? { cache: "no-store" }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the settings and try again.",
    );
  return data;
}
function showNotice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
function render(data) {
  data.settings = normalizeStrategySettings(data.settings);
  current = data;
  const s = data.settings,
    p = data.state.position,
    quote = data.quote || "quote";
  const executionMode = data.execution?.mode || s.mode;
  const modeLabel = executionMode === "demo" ? "Demo mode" : "Paper mode";
  $("execution-mode-label").textContent = modeLabel;
  $("execution-mode-button").dataset.mode = executionMode;
  $("execution-mode-button").setAttribute(
    "aria-label",
    `${modeLabel}. Open execution mode settings`,
  );
  $("status-value").replaceChildren(
    document.createTextNode(
      data.running ? "Running " : data.error || p ? "Paused " : "Ready ",
    ),
  );
  const pill = document.createElement("small");
  pill.className = `pill ${data.running ? "active" : "muted"}`;
  pill.textContent = data.running
    ? "ACTIVE"
    : data.error
      ? "CHECK"
      : p
        ? "PAUSED"
        : "IDLE";
  $("status-value").append(pill);
  $("status-sub").textContent = data.error
    ? "Needs your attention"
    : data.running
      ? `${s.poll_seconds}s polling · ${s.mode === "demo" ? "demo orders" : "simulated fills"}`
      : p
        ? "Position saved · monitoring paused"
        : "Waiting for you to start";
  $("symbol-label").textContent = s.symbol;
  $("market-symbol").textContent = s.symbol;
  $("timeframe-label").textContent = s.timeframe;
  $("price-value").textContent = number(data.price);
  $("mode-label").textContent = s.mode.toUpperCase();
  $("pnl-value").textContent = number(data.state.realized_quote);
  $("position-value").textContent = p
    ? `${p.side === "buy" ? "Long" : "Short"} ${p.remaining}`
    : "Flat";
  $("position-sub").textContent = p
    ? `Entry ${number(p.entry)} · ${quote}`
    : "No active trade";
  $("stop-value").textContent = p ? number(p.stop) : "—";
  $("stop-sub").textContent = p
    ? `${p.stage ? `After TP${p.stage}` : "Initial protection"} · ${quote}`
    : "Moves after each target";
  $("flow-trigger").textContent = `${s.timeframe} candle closes`;
  $("flow-market").textContent = `${s.symbol} · demo feed`;
  $("flow-ema").textContent = `${s.fast_ema} / ${s.slow_ema} periods`;
  $("flow-cmo").textContent = `${s.cmo_length} · ${s.cmo_threshold} cross`;
  $("flow-atr").textContent = `${s.atr_length} periods`;
  $("flow-macro").textContent =
    `${s.higher_timeframe} · ${s.macro_sma ? `SMA ${s.macro_sma}` : "EMA trend"}`;
  $("flow-size").textContent = `${s.contracts} contracts`;
  $("flow-sl").textContent = `${s.sl_atr} × ATR`;
  $("flow-tp").textContent = `${s.tp_atr.join(" / ")} × ATR`;
  $("flow-execution").textContent =
    `${s.mode === "demo" ? "Demo" : "Paper"} execution`;
  $("flow-ready").textContent = data.running
    ? "RUNNING"
    : p
      ? "PAUSED"
      : "READY";
  renderStrategyFlow(s);
  $("ladder-initial").textContent = `SL at ${s.sl_atr} × ATR`;
  $("start-button").disabled = data.running;
  $("stop-button").disabled = !data.running;
  $("start-button").lastChild.textContent =
    ` ${p ? "Resume" : "Start"} ${s.mode === "demo" ? "demo" : "paper"} run`;
  for (let i = 0; i < 4; i++) {
    const reached = Boolean(p && i <= p.stage);
    $(`ladder-${i}`).classList.toggle("reached", reached);
    $(`ladder-${i}`).querySelector(".step-check").textContent = reached
      ? "✓"
      : "○";
  }
  $("event-count").textContent = data.state.events.length;
  const events = [...data.state.events].reverse().slice(0, 12);
  $("events").replaceChildren();
  if (!events.length) {
    const empty = document.createElement("p");
    empty.className = "empty-activity";
    empty.textContent = "Your first event will appear here.";
    $("events").append(empty);
  }
  for (const event of events) {
    const row = document.createElement("div");
    row.className = "event";
    const dot = document.createElement("span");
    const label = document.createElement("b");
    const time = document.createElement("small");
    label.textContent =
      event.kind.replaceAll("_", " ") +
      (event.stop
        ? ` → ${number(event.stop)}`
        : event.price
          ? ` · ${number(event.price)}`
          : "");
    time.textContent = event.time
      ? new Date(event.time * 1000).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })
      : "Reconciled";
    row.append(dot, label, time);
    $("events").append(row);
  }
  showNotice(
    data.error ||
      (s.mode === "paper"
        ? "Paper mode uses Delta demo market data. No exchange orders are sent."
        : "Demo account execution. Initial stop is held at Delta; target monitoring requires the runner to stay active."),
    Boolean(data.error),
  );
  $("feed-status").textContent = data.candles.length
    ? `${data.running ? "● " : "○ "}${data.running ? "Demo feed connected" : "Runner paused · last data"}`
    : "○ Awaiting market data";
  drawChart(data.candles, p);
  document.dispatchEvent(new CustomEvent("runner-status", { detail: data }));
}
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    render(await api("status"));
  } catch {
    showNotice("Dashboard connection lost. Retrying automatically…", true);
    $("start-button").disabled = true;
  } finally {
    polling = false;
  }
}
function svgNode(name, attributes, label) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes))
    el.setAttribute(key, String(value));
  if (label !== undefined) el.textContent = label;
  return el;
}
let marketChartStyle = "area",
  chartInspection = null;
function drawChart(candles, position) {
  const svg = $("chart");
  svg.replaceChildren();
  chartInspection = null;
  $("chart-empty").classList.toggle("hidden", candles.length > 0);
  $("market-chart-tooltip").classList.add("hidden");
  if (!candles.length) return;
  const width = Math.max(240, svg.clientWidth || 700),
    height = 300;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const bars = candles.slice(
      -Math.min(75, Math.max(18, Math.floor(width / 7))),
    ),
    left = 12,
    right = width - 76,
    top = 20,
    bottom = 235;
  let low = Math.min(...bars.map((c) => c.low)),
    high = Math.max(...bars.map((c) => c.high));
  if (position) {
    low = Math.min(low, position.stop, ...position.targets);
    high = Math.max(high, position.stop, ...position.targets);
  }
  const padding = (high - low) * 0.1 || 1;
  high += padding;
  low -= padding;
  const y = (value) => bottom - ((value - low) / (high - low)) * (bottom - top),
    dx = (right - left) / bars.length,
    x = (index) => left + (index + 0.5) * dx;
  for (let i = 0; i < 5; i++) {
    const value = low + ((high - low) * i) / 4,
      lineY = y(value);
    svg.append(
      svgNode("line", {
        x1: left,
        x2: right,
        y1: lineY,
        y2: lineY,
        stroke: "#30313a",
        "stroke-width": 1,
        "stroke-dasharray": "3 5",
      }),
      svgNode(
        "text",
        { x: right + 9, y: lineY + 4, fill: "#a5a6b2", "font-size": 12 },
        number(value, 1),
      ),
    );
  }
  const volumeMax = Math.max(...bars.map((c) => c.volume), 1);
  bars.forEach((c, index) => {
    const cx = x(index),
      color = c.close >= c.open ? "#79d1b2" : "#e49796";
    if (marketChartStyle === "candles") {
      svg.append(
        svgNode("line", {
          x1: cx,
          x2: cx,
          y1: y(c.high),
          y2: y(c.low),
          stroke: color,
          "stroke-width": 1,
        }),
        svgNode("rect", {
          x: cx - dx * 0.28,
          y: Math.min(y(c.open), y(c.close)),
          width: Math.max(dx * 0.56, 1),
          height: Math.max(Math.abs(y(c.open) - y(c.close)), 1),
          fill: color,
        }),
      );
    }
    svg.append(
      svgNode("rect", {
        x: cx - dx * 0.28,
        y: 276 - (c.volume / volumeMax) * 23,
        width: Math.max(1, dx * 0.56),
        height: (c.volume / volumeMax) * 23,
        fill: color,
        opacity: 0.3,
      }),
    );
  });
  if (marketChartStyle === "area") {
    const defs = svgNode("defs", {}),
      gradient = svgNode("linearGradient", {
        id: "market-area-fill",
        x1: "0",
        x2: "0",
        y1: "0",
        y2: "1",
      });
    gradient.append(
      svgNode("stop", {
        offset: "0%",
        "stop-color": "#79d1b2",
        "stop-opacity": 0.23,
      }),
      svgNode("stop", {
        offset: "100%",
        "stop-color": "#79d1b2",
        "stop-opacity": 0,
      }),
    );
    defs.append(gradient);
    svg.append(defs);
    const path = bars
      .map((c, i) => `${i ? "L" : "M"} ${x(i)} ${y(c.close)}`)
      .join(" ");
    svg.append(
      svgNode("path", {
        d: `${path} L ${x(bars.length - 1)} ${bottom} L ${x(0)} ${bottom} Z`,
        fill: "url(#market-area-fill)",
      }),
      svgNode("path", {
        d: path,
        fill: "none",
        stroke: "#79d1b2",
        "stroke-width": 1.8,
        "stroke-linejoin": "round",
      }),
      svgNode("circle", {
        cx: x(bars.length - 1),
        cy: y(bars.at(-1).close),
        r: 3,
        fill: "#baf4dd",
        stroke: "#294f3f",
        "stroke-width": 3,
      }),
    );
  }
  for (const index of [
    ...new Set([
      0,
      Math.floor(bars.length / 3),
      Math.floor((2 * bars.length) / 3),
      bars.length - 1,
    ]),
  ]) {
    svg.append(
      svgNode(
        "text",
        {
          x: x(index),
          y: 296,
          fill: "#a5a6b2",
          "font-size": 12,
          "text-anchor":
            index === 0
              ? "start"
              : index === bars.length - 1
                ? "end"
                : "middle",
        },
        new Date(bars[index].time * 1000).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      ),
    );
  }
  if (position) {
    const levels = [
      [position.entry, "Entry", "#b3a0ef"],
      [position.stop, "SL", "#f09a97"],
      ...position.targets.map((value, i) => [value, `TP${i + 1}`, "#9bd8b1"]),
    ];
    for (const [value, label, color] of levels) {
      svg.append(
        svgNode("line", {
          x1: left,
          x2: right,
          y1: y(value),
          y2: y(value),
          stroke: color,
          "stroke-dasharray": "4 5",
          "stroke-width": 1,
        }),
        svgNode(
          "text",
          { x: left + 5, y: y(value) - 5, fill: color, "font-size": 12 },
          `${label} ${number(value)}`,
        ),
      );
    }
  }
  const change = (bars.at(-1).close / bars[0].open - 1) * 100;
  $("chart-close-price").textContent = number(bars.at(-1).close);
  $("chart-window-change").textContent =
    `${change > 0 ? "+" : ""}${number(change)}% · ${bars.length} candles`;
  $("chart-window-change").classList.toggle("positive", change >= 0);
  $("chart-window-change").classList.toggle("negative", change < 0);
  $("last-candle").textContent =
    `Last closed ${new Date(bars.at(-1).time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  chartInspection = { bars, x, y, left, right, top, bottom, width, height };
}
const timeframes = [
  "1m",
  "3m",
  "5m",
  "15m",
  "30m",
  "1h",
  "2h",
  "4h",
  "6h",
  "1d",
];
const timeframeSeconds = Object.fromEntries(
  timeframes.map((value) => [
    value,
    parseInt(value, 10) * { m: 60, h: 3600, d: 86400 }[value.at(-1)],
  ]),
);
const fields = [
  ["strategy", "mode", "Execution mode", ["paper", "demo"]],
  ["strategy", "symbol", "Market symbol", "text"],
  ["strategy", "timeframe", "Signal timeframe", timeframes],
  ["strategy", "higher_timeframe", "Higher timeframe", timeframes],
  ["strategy", "strategy", "Entry strategy", Object.keys(STRATEGY_NAMES)],
  ["strategy", "fast_ema", "Fast EMA", "number", 2, 200],
  ["strategy", "slow_ema", "Slow EMA", "number", 3, 500],
  ["strategy", "cmo_length", "CMO length", "number", 2, 200],
  [
    "strategy",
    "cmo_threshold",
    "CMO cross threshold (±)",
    "number",
    0,
    90,
    0.1,
  ],
  ["strategy", "atr_length", "ATR length", "number", 2, 200],
  ["strategy", "macro_sma", "Higher-timeframe SMA (0 = off)", "number", 0, 500],
  ["strategy", "poll_seconds", "Poll interval (seconds)", "number", 2, 60],
  ["risk", "sl_atr", "Initial SL (× ATR)", "number", 0.1, 20, 0.1],
  ["risk", "tp0", "TP1 (× ATR)", "number", 0.1, 50, 0.1],
  ["risk", "tp1", "TP2 (× ATR)", "number", 0.1, 50, 0.1],
  ["risk", "tp2", "TP3 (× ATR)", "number", 0.1, 50, 0.1],
  ["risk", "contracts", "Contracts per trade", "number", 4, 10000],
  ["risk", "max_contracts", "Maximum position contracts", "number", 4, 10000],
  ["risk", "leverage", "Demo leverage (×)", "number", 1, 50],
  [
    "risk",
    "max_notional_quote",
    "Maximum quote notional",
    "number",
    1,
    1000000,
    0.1,
  ],
  [
    "risk",
    "max_loss_quote",
    "Bot realized-loss limit (quote)",
    "number",
    1,
    100000,
    0.1,
  ],
  [
    "risk",
    "max_entry_slippage_bps",
    "Maximum entry slippage (bps)",
    "number",
    0.1,
    500,
    0.1,
  ],
  ["risk", "paper_fee_bps", "Paper fee estimate (bps)", "number", 0, 100, 0.1],
  ...EXTRA_STRATEGY_FIELDS,
];
for (const [section, key, title, kind, min, max, step] of fields) {
  const label = document.createElement("label");
  label.className = "field";
  label.textContent = title;
  const input = document.createElement(
    Array.isArray(kind) ? "select" : "input",
  );
  input.id = `setting-${key}`;
  input.name = key;
  if (Array.isArray(kind)) {
    for (const value of kind) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent =
        key === "strategy"
          ? STRATEGY_NAMES[value]
          : key === "mode"
            ? value === "paper"
              ? "Paper — local simulation"
              : "Demo — orders at Delta demo"
            : value.replaceAll("_", " ");
      input.append(option);
    }
  } else {
    input.type = kind;
    if (kind === "number") {
      input.min = min;
      input.max = max;
      input.step = step || 1;
    }
  }
  input.required = true;
  if (key === "symbol") {
    input.placeholder = "BTCUSD or ETHUSD";
    input.maxLength = 60;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.addEventListener("blur", () => {
      input.value = input.value.trim().toUpperCase();
    });
  }
  input.addEventListener("input", () => input.removeAttribute("aria-invalid"));
  label.append(input);
  $(`${section}-inputs`).append(label);
}
function selectTab(name) {
  document.querySelectorAll("#settings-dialog [data-tab]").forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle("selected", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  for (const tab of ["strategy", "risk", "connection"])
    $(`${tab}-fields`).classList.toggle("hidden", tab !== name);
  $("save-settings").classList.toggle("hidden", name === "connection");
}
function wireTabs(selector, dataKey, onSelect) {
  const buttons = [...document.querySelectorAll(selector)];
  buttons.forEach((button, index) => {
    button.onclick = () => onSelect(button.dataset[dataKey]);
    button.onkeydown = (event) => {
      const offsets = {
        ArrowRight: (index + 1) % buttons.length,
        ArrowLeft: (index + buttons.length - 1) % buttons.length,
        Home: 0,
        End: buttons.length - 1,
      };
      if (!(event.key in offsets)) return;
      event.preventDefault();
      const next = buttons[offsets[event.key]];
      onSelect(next.dataset[dataKey]);
      next.focus();
    };
  });
}
function readSettings(base, prefix = "setting-") {
  const settings = normalizeStrategySettings(structuredClone(base));
  for (const [, key, , kind] of fields) {
    const input = $(`${prefix}${key}`);
    if (!input || input.disabled) continue;
    if (key === "symbol") input.value = input.value.trim().toUpperCase();
    const value = kind === "number" ? Number(input.value) : input.value;
    if (key.startsWith("tp")) settings.tp_atr[Number(key[2])] = value;
    else settings[key] = value;
  }
  return settings;
}
function settingsIssue(s) {
  if (!/^[A-Z0-9_-]{3,60}$/.test(s.symbol))
    return {
      key: "symbol",
      message: "Enter a Delta market symbol, such as BTCUSD or ETHUSD.",
    };
  if (
    (isLegacyStrategy(s.strategy) || s.htf_filter === "enabled") &&
    timeframeSeconds[s.higher_timeframe] <= timeframeSeconds[s.timeframe]
  )
    return {
      key: "higher_timeframe",
      message: "Higher timeframe must be larger than the signal timeframe.",
    };
  if (s.fast_ema >= s.slow_ema)
    return {
      key: "fast_ema",
      message: "Fast EMA must be shorter than slow EMA.",
    };
  if (s.trend_fast_period >= s.trend_slow_period)
    return {
      key: "trend_fast_period",
      message: "Trend fast EMA must be shorter than trend slow EMA.",
    };
  if (
    !(s.rsi_oversold < s.rsi_exit_level && s.rsi_exit_level < s.rsi_overbought)
  )
    return {
      key: "rsi_exit_level",
      message: "RSI levels must satisfy oversold < exit < overbought.",
    };
  if (
    !(0 < s.tp_atr[0] && s.tp_atr[0] < s.tp_atr[1] && s.tp_atr[1] < s.tp_atr[2])
  )
    return {
      key: "tp0",
      message: "Set targets in increasing order: TP1 < TP2 < TP3.",
    };
  if (s.sizing_mode === "fixed_contracts" && s.contracts > s.max_contracts)
    return {
      key: "max_contracts",
      message: "Maximum position contracts must cover the contracts per trade.",
    };
  return null;
}
function updateRiskPreview(prefix, id) {
  const value = (key) => Number($(`${prefix}${key}`).value);
  const stop = value("sl_atr"),
    targets = [0, 1, 2].map((i) => value(`tp${i}`)),
    contracts = value("contracts");
  const valid =
    stop > 0 &&
    targets[0] > 0 &&
    targets[1] > targets[0] &&
    targets[2] > targets[1] &&
    Number.isInteger(contracts) &&
    contracts >= 4;
  $(id).textContent = valid
    ? `Target reward/risk: ${targets.map((n) => `${number(n / stop)}R`).join(" / ")}. Partial exits: ${Math.floor(contracts / 2)} / ${Math.floor(contracts / 4)} / ${contracts - Math.floor(contracts / 2) - Math.floor(contracts / 4)} contracts.`
    : "Set a positive stop, increasing targets, and at least four contracts to preview this trade.";
  if ($(prefix + "sizing_mode")?.value === "risk_percent")
    $(id).textContent =
      "Planned risk " +
      $(prefix + "risk_per_trade_percent").value +
      "% with a " +
      $(prefix + "max_contracts").value +
      "-contract cap. Quantity includes stop distance and cost reserves; trades below four " +
      "contracts are skipped. TP1 → entry, TP2 → TP1; gaps can exceed planned risk.";
}
function revealSettingsError(input, message) {
  const section = input.closest(".form-section");
  if (section) selectTab(section.id.replace("-fields", ""));
  $("form-error").textContent = message;
  input.setAttribute("aria-invalid", "true");
  input.focus();
}
function openSettings(tab = "strategy") {
  if (!current) return;
  const s = current.settings;
  for (const [, key] of fields)
    $(`setting-${key}`).value = key.startsWith("tp")
      ? s.tp_atr[Number(key[2])]
      : s[key];
  updateStrategyFields("setting-");
  $("credential-status").textContent = current.credentials_configured
    ? "Demo credentials are saved. Fields stay empty to protect your secrets."
    : "No demo credentials saved. Paper mode works without them.";
  $("form-error").textContent = "";
  updateRiskPreview("setting-", "ratio-note");
  selectTab(tab);
  $("settings-dialog").showModal();
}
$("settings-button").onclick = () => openSettings();
$("strategy-tab").onclick = () => openSettings();
$("chart-settings").onclick = () => openSettings();
$("connection-button").onclick = () => openSettings("connection");
$("execution-mode-button").onclick = () => openSettings("strategy");
$("close-settings").onclick = () => $("settings-dialog").close();
wireTabs("#settings-dialog [data-tab]", "tab", selectTab);
$("settings-form").addEventListener("input", () =>
  updateRiskPreview("setting-", "ratio-note"),
);
$("settings-form").addEventListener(
  "invalid",
  (event) => {
    event.preventDefault();
    revealSettingsError(event.target, event.target.validationMessage);
  },
  true,
);
$("activity-tab").onclick = () =>
  $("activity").scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
  });
$("overview-tab").onclick = () =>
  window.scrollTo({ top: 0, behavior: "smooth" });
let settingsSaving = false;
$("settings-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!$("connection-fields").classList.contains("hidden")) {
    $("save-connection").click();
    return;
  }
  if (settingsSaving) return;
  const s = readSettings(current.settings);
  const issue = settingsIssue(s);
  if (issue) {
    revealSettingsError($(`setting-${issue.key}`), issue.message);
    return;
  }
  settingsSaving = true;
  $("save-settings").disabled = true;
  $("save-settings").textContent = "Saving settings…";
  $("form-error").textContent = "";
  try {
    await api("settings", s);
    $("settings-dialog").close();
    toast("Settings saved. Ready for your next run.");
    await refresh();
  } catch (error) {
    $("form-error").textContent = error.message;
  } finally {
    settingsSaving = false;
    $("save-settings").disabled = false;
    $("save-settings").textContent = "Save settings ↗";
  }
};
let connectionSaving = false;
$("connection-fields").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.matches("input")) {
    event.preventDefault();
    $("save-connection").click();
  }
});
$("save-connection").onclick = async () => {
  if (connectionSaving) return;
  for (const id of ["api-key", "api-secret"]) {
    if (!$(id).value.trim()) {
      revealSettingsError(
        $(id),
        "Enter both the demo API key and its matching secret.",
      );
      return;
    }
  }
  connectionSaving = true;
  $("form-error").textContent = "";
  $("save-connection").disabled = true;
  $("save-connection").textContent = "Saving connection…";
  $("test-connection").disabled = true;
  try {
    await api("credentials", {
      api_key: $("api-key").value,
      api_secret: $("api-secret").value,
    });
    $("api-key").value = "";
    $("api-secret").value = "";
    $("credential-status").textContent =
      "Demo credentials saved on this computer.";
    toast("Demo connection saved.");
    await refresh();
    document.dispatchEvent(new Event("credentials-saved"));
  } catch (error) {
    $("form-error").textContent = error.message;
  } finally {
    connectionSaving = false;
    $("save-connection").disabled = false;
    $("save-connection").textContent = "Save demo connection";
    $("test-connection").disabled = false;
  }
};
async function start(confirmDemo = false) {
  try {
    await api("start", {
      expected_mode: current.settings.mode,
      confirm_demo: confirmDemo,
    });
    toast("Runner starting. Checking demo market data…");
    await refresh();
  } catch (error) {
    showNotice(error.message, true);
  }
}
$("start-button").onclick = () => {
  if (current.settings.mode === "demo") {
    if (!current.credentials_configured) {
      openSettings("connection");
      return;
    }
    $("confirm-dialog").showModal();
  } else start();
};
$("cancel-confirm").onclick = () => $("confirm-dialog").close();
$("accept-confirm").onclick = () => {
  $("confirm-dialog").close();
  start(true);
};
$("stop-button").onclick = async () => {
  try {
    await api("stop", {});
    toast("Runner paused. Existing demo stop remains at Delta.");
    await refresh();
  } catch (error) {
    showNotice(error.message, true);
  }
};
$("reconcile-button").onclick = async () => {
  if (
    !window.confirm(
      "Clear the local position record? In demo mode this first verifies that the selected product has no position or open orders. Paper mode clears the simulated position.",
    )
  )
    return;
  try {
    await api("reconcile", {});
    toast("Flat account reconciled.");
    await refresh();
  } catch (error) {
    showNotice(error.message, true);
  }
};
refresh();
setInterval(refresh, 2500);
