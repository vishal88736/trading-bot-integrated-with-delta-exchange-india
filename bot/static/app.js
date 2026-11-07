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
  current = data;
  const s = data.settings,
    p = data.state.position,
    quote = data.quote || "quote";
  $("status-value").replaceChildren(
    document.createTextNode(
      data.running ? "Running " : data.error ? "Paused " : "Ready ",
    ),
  );
  const pill = document.createElement("small");
  pill.className = `pill ${data.running ? "active" : "muted"}`;
  pill.textContent = data.running ? "ACTIVE" : data.error ? "CHECK" : "IDLE";
  $("status-value").append(pill);
  $("status-sub").textContent = data.error
    ? "Needs your attention"
    : data.running
      ? `${s.poll_seconds}s polling · ${s.mode === "demo" ? "demo orders" : "simulated fills"}`
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
  $("flow-ready").textContent = data.running ? "RUNNING" : "READY";
  $("ladder-initial").textContent = `SL at ${s.sl_atr} × ATR`;
  $("start-button").disabled = data.running;
  $("stop-button").disabled = !data.running;
  $("start-button").lastChild.textContent =
    ` Start ${s.mode === "demo" ? "demo" : "paper"} run`;
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
function drawChart(candles, position) {
  const svg = $("chart");
  svg.replaceChildren();
  $("chart-empty").classList.toggle("hidden", candles.length > 0);
  if (!candles.length) return;
  const width = Math.max(320, svg.clientWidth || 700);
  svg.setAttribute("viewBox", `0 0 ${width} 430`);
  const bars = candles.slice(-Math.min(75, Math.floor(width / 7))),
    left = 10,
    right = width - 100,
    top = 26,
    bottom = 348;
  let low = Math.min(...bars.map((c) => c.low)),
    high = Math.max(...bars.map((c) => c.high));
  if (position) {
    low = Math.min(low, position.stop, ...position.targets);
    high = Math.max(high, position.stop, ...position.targets);
  }
  const padding = (high - low) * 0.09 || 1;
  high += padding;
  low -= padding;
  const y = (value) => bottom - ((value - low) / (high - low)) * (bottom - top),
    dx = (right - left) / bars.length;
  for (let i = 0; i < 6; i++) {
    const value = low + ((high - low) * i) / 5,
      lineY = y(value);
    svg.append(
      svgNode("line", {
        x1: left,
        x2: right,
        y1: lineY,
        y2: lineY,
        stroke: "#eef1e9",
        "stroke-width": 1,
      }),
      svgNode(
        "text",
        { x: right + 10, y: lineY + 3, fill: "#53645b", "font-size": 12 },
        number(value, 1),
      ),
    );
  }
  const volumeMax = Math.max(...bars.map((c) => c.volume), 1);
  bars.forEach((c, index) => {
    const x = left + (index + 0.5) * dx,
      color = c.close >= c.open ? "#77b499" : "#d08c80";
    svg.append(
      svgNode("line", {
        x1: x,
        x2: x,
        y1: y(c.high),
        y2: y(c.low),
        stroke: color,
        "stroke-width": 1,
      }),
      svgNode("rect", {
        x: x - dx * 0.28,
        y: Math.min(y(c.open), y(c.close)),
        width: Math.max(dx * 0.56, 1),
        height: Math.max(Math.abs(y(c.open) - y(c.close)), 1),
        fill: color,
      }),
      svgNode("rect", {
        x: x - dx * 0.28,
        y: 405 - (c.volume / volumeMax) * 36,
        width: dx * 0.56,
        height: (c.volume / volumeMax) * 36,
        fill: color,
        opacity: 0.36,
      }),
    );
    if (index % 15 === 0)
      svg.append(
        svgNode(
          "text",
          {
            x,
            y: 425,
            fill: "#53645b",
            "font-size": 12,
            "text-anchor": "middle",
          },
          new Date(c.time * 1000).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          }),
        ),
      );
  });
  if (position) {
    const levels = [
      [position.entry, "Entry", "#435c87"],
      [position.stop, "SL", "#a04435"],
      ...position.targets.map((value, i) => [value, `TP${i + 1}`, "#2d6c45"]),
    ];
    for (const [value, label, color] of levels)
      svg.append(
        svgNode("line", {
          x1: left,
          x2: right,
          y1: y(value),
          y2: y(value),
          stroke: color,
          "stroke-dasharray": "4 4",
          "stroke-width": 1,
        }),
        svgNode(
          "text",
          { x: left + 5, y: y(value) - 5, fill: color, "font-size": 12 },
          `${label} ${number(value)}`,
        ),
      );
  }
  $("last-candle").textContent =
    `Last closed ${new Date(bars.at(-1).time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
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
const fields = [
  ["strategy", "mode", "Execution mode", ["paper", "demo"]],
  ["strategy", "symbol", "Market symbol", "text"],
  ["strategy", "timeframe", "Signal timeframe", timeframes],
  ["strategy", "higher_timeframe", "Higher timeframe", timeframes],
  [
    "strategy",
    "strategy",
    "Entry strategy",
    ["trend_signals", "custom_strategy"],
  ],
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
      option.textContent = value.replaceAll("_", " ");
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
  label.append(input);
  $(`${section}-inputs`).append(label);
}
function selectTab(name) {
  document
    .querySelectorAll(".dialog-tabs button")
    .forEach((button) =>
      button.classList.toggle("selected", button.dataset.tab === name),
    );
  for (const tab of ["strategy", "risk", "connection"])
    $(`${tab}-fields`).classList.toggle("hidden", tab !== name);
}
function openSettings(tab = "strategy") {
  if (!current) return;
  const s = current.settings;
  for (const [, key] of fields)
    $(`setting-${key}`).value = key.startsWith("tp")
      ? s.tp_atr[Number(key[2])]
      : s[key];
  $("credential-status").textContent = current.credentials_configured
    ? "Demo credentials are saved. Fields stay empty to protect your secrets."
    : "No demo credentials saved. Paper mode works without them.";
  $("form-error").textContent = "";
  $("ratio-note").textContent =
    `With your saved settings: TP reward/risk = ${s.tp_atr.map((n) => `${number(n / s.sl_atr, 2)}R`).join(" / ")}. Targets split ${Math.floor(s.contracts / 2)} / ${Math.floor(s.contracts / 4)} / ${s.contracts - Math.floor(s.contracts / 2) - Math.floor(s.contracts / 4)} contracts.`;
  selectTab(tab);
  $("settings-dialog").showModal();
}
$("settings-button").onclick = () => openSettings();
$("strategy-tab").onclick = () => openSettings();
$("chart-settings").onclick = () => openSettings();
$("connection-button").onclick = () => openSettings("connection");
$("close-settings").onclick = () => $("settings-dialog").close();
document
  .querySelectorAll(".dialog-tabs button")
  .forEach((button) => (button.onclick = () => selectTab(button.dataset.tab)));
$("activity-tab").onclick = () =>
  $("activity").scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
  });
$("overview-tab").onclick = () =>
  window.scrollTo({ top: 0, behavior: "smooth" });
$("settings-form").onsubmit = async (event) => {
  event.preventDefault();
  const s = structuredClone(current.settings);
  for (const [, key, , kind] of fields) {
    const value =
      kind === "number"
        ? Number($(`setting-${key}`).value)
        : $(`setting-${key}`).value;
    if (key.startsWith("tp")) s.tp_atr[Number(key[2])] = value;
    else s[key] = value;
  }
  try {
    await api("settings", s);
    $("settings-dialog").close();
    toast("Settings saved. Ready for your next run.");
    await refresh();
  } catch (error) {
    $("form-error").textContent = error.message;
  }
};
$("save-connection").onclick = async () => {
  try {
    await api("credentials", {
      api_key: $("api-key").value,
      api_secret: $("api-secret").value,
    });
    $("api-key").value = "";
    $("api-secret").value = "";
    $("credential-status").textContent =
      "Demo credentials saved securely on this computer.";
    toast("Demo connection saved.");
    await refresh();
    document.dispatchEvent(new Event("credentials-saved"));
  } catch (error) {
    $("form-error").textContent = error.message;
  }
};
async function start() {
  try {
    await api("start", {});
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
  start();
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
