/* Presentation and read-only market previews. Execution remains in app.js. */
let studioPreview = null,
  studioMarketLoading = false,
  studioSearchReturn = null;
const mobileSidebar = window.matchMedia("(max-width: 900px)");

function setSidebar(open, returnFocus = true) {
  const expanded = Boolean(open && mobileSidebar.matches);
  $("workspace-sidebar").dataset.open = String(expanded);
  $("workspace-sidebar").inert = mobileSidebar.matches && !expanded;
  $("sidebar-toggle").setAttribute("aria-expanded", String(expanded));
  $("sidebar-toggle").setAttribute(
    "aria-label",
    expanded ? "Close navigation" : "Open navigation",
  );
  $("sidebar-backdrop").classList.toggle("hidden", !expanded);
  document.body.classList.toggle("sidebar-open", expanded);
  $("main-content").inert = expanded;
  document.querySelector(".topbar").inert = expanded;
  if (expanded) $("overview-tab").focus();
  else if (returnFocus && mobileSidebar.matches) $("sidebar-toggle").focus();
}
$("sidebar-toggle").onclick = () =>
  setSidebar($("sidebar-toggle").getAttribute("aria-expanded") !== "true");
$("sidebar-backdrop").onclick = () => setSidebar(false);
$("workspace-sidebar").addEventListener(
  "click",
  (event) => {
    if (event.target.closest("button,a")) setSidebar(false, false);
  },
  { capture: true },
);
mobileSidebar.addEventListener?.("change", () => setSidebar(false, false));
setSidebar(false, false);

function studioAction(action) {
  setSidebar(false, false);
  if (action === "settings") openSettings("strategy");
  else if (action === "connection") openSettings("connection");
  else if (action === "activity") {
    showView("automation");
    $("activity").scrollIntoView({ behavior: "auto", block: "start" });
  } else showView(action);
}
for (const button of document.querySelectorAll("[data-studio-action]"))
  button.onclick = () => studioAction(button.dataset.studioAction);

function updateBacktestDataSummary() {
  const sources = {india_public:"Public market data", demo:"Demo market data"};
  const caches = {use:"cached candles", refresh:"fresh download", off:"cache bypassed"};
  const samples = Number($("research-lookahead").value);
  $("backtest-data-summary").textContent = [
    sources[$("backtest-source").value], caches[$("research-cache").value],
    samples ? `${samples} checkpoints` : "signal check off",
  ].join(" · ");
}
for (const id of ["backtest-source", "research-cache", "research-lookahead"])
  $(id).addEventListener("change", updateBacktestDataSummary);
updateBacktestDataSummary();

const studioCommands = [
  {
    label: "Trading overview",
    detail: "Market & automation",
    action: "automation",
    keywords: "dashboard chart market overview",
  },
  {
    label: "Funds & holdings",
    detail: "Demo account",
    action: "account",
    keywords: "wallet account positions balance",
  },
  {
    label: "Backtesting",
    detail: "Free historical research",
    action: "backtest",
    keywords: "backtest history research strategies",
  },
  {
    label: "Strategy settings",
    detail: "Your entries, exits & risk",
    action: "settings",
    keywords: "strategy settings targets stop risk",
  },
  {
    label: "Connection settings",
    detail: "Delta demo account",
    action: "connection",
    keywords: "api connect credentials demo",
  },
  {
    label: "Activity log",
    detail: "Runner events",
    action: "activity",
    keywords: "activity log events",
  },
];
function renderStudioCommands() {
  const query = $("workspace-search-input").value.trim().toLowerCase();
  const results = studioCommands.filter((c) =>
    `${c.label} ${c.keywords}`.toLowerCase().includes(query),
  );
  $("workspace-search-results").replaceChildren();
  for (const item of results) {
    const button = document.createElement("button"),
      label = document.createElement("span"),
      detail = document.createElement("small");
    button.type = "button";
    label.textContent = item.label;
    detail.textContent = item.detail;
    button.append(label, detail);
    button.onclick = () => {
      closeStudioSearch(false);
      studioAction(item.action);
    };
    $("workspace-search-results").append(button);
  }
  if (!results.length) {
    const empty = document.createElement("p");
    empty.textContent =
      "No matching page. Try account, backtesting, strategy, or activity.";
    $("workspace-search-results").append(empty);
  }
}
function openStudioSearch(trigger = null) {
  if (document.querySelector("dialog[open]")) return;
  studioSearchReturn =
    $("workspace-sidebar").dataset.open === "true"
      ? $("sidebar-toggle")
      : trigger || document.activeElement;
  setSidebar(false, false);
  $("workspace-search-input").value = "";
  renderStudioCommands();
  $("workspace-search-dialog").showModal();
  $("workspace-search-input").focus();
}
function closeStudioSearch(restoreFocus = true) {
  if (!$("workspace-search-dialog").open) return;
  $("workspace-search-dialog").close();
  if (restoreFocus) studioSearchReturn?.focus();
}
$("workspace-search-open").onclick = () =>
  openStudioSearch($("workspace-search-open"));
$("workspace-search-close").onclick = () => closeStudioSearch();
$("workspace-search-input").oninput = renderStudioCommands;
$("workspace-search-dialog").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    closeStudioSearch();
    return;
  }
  const buttons = [...$("workspace-search-results").querySelectorAll("button")];
  if (!buttons.length) return;
  if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement);
    const next =
      index < 0
        ? event.key === "ArrowDown"
          ? 0
          : buttons.length - 1
        : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) %
          buttons.length;
    buttons[next].focus();
  } else if (
    event.key === "Enter" &&
    document.activeElement === $("workspace-search-input")
  ) {
    event.preventDefault();
    buttons[0].click();
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openStudioSearch();
  }
  if ($("workspace-sidebar").dataset.open !== "true") return;
  if (event.key === "Escape") {
    event.preventDefault();
    setSidebar(false);
  }
  if (event.key === "Tab") {
    const controls = [...$("workspace-sidebar").querySelectorAll("a,button")];
    const first = controls[0],
      last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
document.addEventListener("workspace-view", (event) => {
  const label = {
    automation: "Overview",
    account: "Funds & holdings",
    backtest: "Backtesting",
  }[event.detail];
  $("workspace-page-label").textContent = label;
  document.title = `Delta Studio · ${label}`;
  setSidebar(false, false);
  if (event.detail === "automation") refreshStudioMarket();
});
$("workspace-page-label").textContent = {
  automation: "Overview",
  account: "Funds & holdings",
  backtest: "Backtesting",
}[activeView];
document.title = `Delta Studio · ${$("workspace-page-label").textContent}`;

function renderStudioRunner(data) {
  const s = data.settings,
    p = data.state.position;
  const paper = data.execution ? data.execution.simulation : s.mode === "paper";
  $("position-source-label").textContent =
    `${paper ? "Local paper simulation" : "Demo runner position"} · ${data.running ? "monitoring" : "runner paused"}`;
  $("position-market-label").textContent = s.symbol;
  $("position-next-target").textContent = p
    ? `TP${p.stage + 1} · ${number(p.targets[p.stage])}`
    : "—";
  $("position-monitor-dot").classList.toggle("gray", !(p && data.running));
  $("monitor-status")
    .querySelector(".dot")
    .classList.toggle("gray", !(p && data.running));
  $("monitor-status-label").textContent = p
    ? data.running
      ? "Monitoring target progression"
      : "Position saved · target monitoring paused"
    : "Waiting for a trade";
  $("strategy-focus-name").textContent = STRATEGY_NAMES[s.strategy];
  $("strategy-focus-timeframes").textContent =
    `${s.timeframe} signals · ${s.htf_filter === "disabled" && !["trend_signals", "custom_strategy"].includes(s.strategy) ? "higher-timeframe filter off" : s.higher_timeframe + " confirmation"}`;
  const knownSize = p || s.sizing_mode !== "risk_percent";
  const quantities = p
    ? p.quantities
    : knownSize
      ? [
          Math.floor(s.contracts / 2),
          Math.floor(s.contracts / 4),
          s.contracts -
            Math.floor(s.contracts / 2) -
            Math.floor(s.contracts / 4),
        ]
      : [50, 25, 25];
  const total = quantities.reduce((a, b) => a + b, 0),
    first = (quantities[0] / total) * 100,
    second = ((quantities[0] + quantities[1]) / total) * 100;
  $("allocation-ring").style.background =
    `conic-gradient(#79d1b2 0% ${first}%, #e5ba68 ${first}% ${second}%, #b3a0ef ${second}% 100%)`;
  $("allocation-ring").setAttribute(
    "aria-label",
    quantities
      .map((q, i) => `TP${i + 1}: ${number((q / total) * 100, 1)} percent`)
      .join(", "),
  );
  $("allocation-center-label").textContent = p
    ? "Open contracts"
    : "Exit stages";
  $("allocation-center-value").textContent = p ? p.remaining : "3";
  $("allocation-caption").textContent = p
    ? "Original entry allocation · integer contract sizes"
    : knownSize
      ? `${s.contracts} contracts · planned allocation`
      : "Risk-sized at entry · minimum four contracts";
  $("allocation-legend").replaceChildren();
  for (let i = 0; i < 3; i++) {
    const group = document.createElement("div"),
      label = document.createElement("dt"),
      value = document.createElement("dd"),
      dot = document.createElement("i");
    dot.style.background = ["#79d1b2", "#e5ba68", "#b3a0ef"][i];
    label.append(dot, document.createTextNode(`TP${i + 1}`));
    value.textContent = knownSize
      ? `${quantities[i]} · ${number((quantities[i] / total) * 100, 0)}%`
      : `${quantities[i]}%`;
    group.append(label, value);
    $("allocation-legend").append(group);
  }
  paintStudioMarket();
}

function drawStudioVolume(candles) {
  const svg = $("market-volume-chart"),
    bars = candles.slice(-24);
  svg.replaceChildren();
  $("volume-empty").classList.toggle("hidden", bars.length > 0);
  if (!bars.length) {
    $("volume-total").textContent = "—";
    return;
  }
  const width = Math.max(220, svg.clientWidth || 440),
    height = 110,
    left = 4,
    right = width - 4;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const maximum = Math.max(...bars.map((c) => c.volume), 1),
    dx = (right - left) / bars.length;
  bars.forEach((c, i) => {
    const high = (c.volume / maximum) * 70;
    svg.append(
      svgNode("rect", {
        x: left + i * dx + 1,
        y: 83 - high,
        width: Math.max(1, dx - 3),
        height: Math.max(1, high),
        rx: 1,
        fill: c.close >= c.open ? "#69b79b" : "#a06d6f",
        opacity: 0.75,
      }),
    );
  });
  for (const index of [0, Math.floor((bars.length - 1) / 2), bars.length - 1]) {
    svg.append(
      svgNode(
        "text",
        {
          x: left + (index + 0.5) * dx,
          y: 104,
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
  $("volume-total").textContent = number(
    bars.reduce((sum, c) => sum + c.volume, 0),
    0,
  );
  $("volume-caption").textContent =
    `${bars.length} closed candles · exchange-reported units`;
}

function paintStudioMarket() {
  if (!current) return;
  const validPreview =
    studioPreview?.symbol === current.settings.symbol &&
    studioPreview?.resolution === current.settings.timeframe;
  const usingPreview = validPreview && !current.running;
  const candles = usingPreview ? studioPreview.candles : current.candles;
  drawStudioVolume(candles);
  if (usingPreview) {
    drawChart(candles, current.state.position);
    $("price-value").textContent = number(studioPreview.price);
    $("price-sub").textContent =
      `${studioPreview.stale ? "Cached demo preview" : "Read-only demo preview"} · ${studioPreview.quote}`;
    $("feed-status").textContent = studioPreview.stale
      ? "○ Preview stale · retry refresh"
      : "● Read-only demo preview";
    $("chart-caption").textContent = studioPreview.stale
      ? "Cached preview · last update failed"
      : `Public demo data · updated ${new Date(studioPreview.fetched_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    if (current.state.position) {
      const p = current.state.position;
      $("position-sub").textContent =
        `Entry ${number(p.entry)} · ${studioPreview.quote}`;
      $("stop-sub").textContent =
        `${p.stage ? `After TP${p.stage}` : "Initial protection"} · ${studioPreview.quote}`;
    }
  } else if (current.candles.length) {
    $("chart-caption").textContent =
      `Closed ${current.settings.timeframe} candles · ${current.running ? "runner monitoring" : "saved runner data"}`;
    $("price-sub").textContent = "Demo market feed";
  }
}
async function refreshStudioMarket() {
  if (
    !current ||
    current.running ||
    activeView !== "automation" ||
    studioMarketLoading
  )
    return;
  studioMarketLoading = true;
  $("market-refresh").disabled = true;
  try {
    const data = await api("market");
    if (!data.read_only || !Array.isArray(data.candles))
      throw new Error("No preview data");
    if (
      data.symbol !== current?.settings.symbol ||
      data.resolution !== current?.settings.timeframe
    )
      return;
    studioPreview = data;
    paintStudioMarket();
  } catch {
    if (studioPreview) {
      studioPreview = { ...studioPreview, stale: true };
      paintStudioMarket();
    }
    if (
      current &&
      !current.running &&
      !current.candles.length &&
      !studioPreview
    ) {
      $("chart-empty").querySelector("p").textContent =
        "Market preview unavailable. Use ↻ to retry. Your runner stays paused.";
      $("feed-status").textContent = "○ Preview unavailable · retry";
    }
  } finally {
    studioMarketLoading = false;
    $("market-refresh").disabled = false;
  }
}
$("market-refresh").onclick = refreshStudioMarket;
document.addEventListener("runner-status", (event) => {
  const changedMarket =
    studioPreview &&
    (studioPreview.symbol !== event.detail.settings.symbol ||
      studioPreview.resolution !== event.detail.settings.timeframe);
  if (changedMarket) studioPreview = null;
  renderStudioRunner(event.detail);
  if (changedMarket || !studioPreview) refreshStudioMarket();
});
for (const button of document.querySelectorAll("[data-chart-style]")) {
  button.onclick = () => {
    marketChartStyle = button.dataset.chartStyle;
    for (const item of document.querySelectorAll("[data-chart-style]"))
      item.setAttribute("aria-pressed", String(item === button));
    drawChart(current?.candles || [], current?.state.position);
    paintStudioMarket();
  };
}

function inspectStudioCandle(index) {
  if (!chartInspection) return;
  const { bars, x, y, top, bottom } = chartInspection;
  index = Math.max(0, Math.min(bars.length - 1, index));
  const c = bars[index],
    svg = $("chart");
  chartInspection.selected = index;
  svg.querySelector("[data-inspection]")?.remove();
  const group = svgNode("g", {
    "data-inspection": "true",
    "pointer-events": "none",
  });
  group.append(
    svgNode("line", {
      x1: x(index),
      x2: x(index),
      y1: top,
      y2: bottom,
      stroke: "#bac9c2",
      "stroke-dasharray": "3 4",
    }),
    svgNode("circle", {
      cx: x(index),
      cy: y(c.close),
      r: 4,
      fill: "#d6fbe9",
      stroke: "#538e73",
      "stroke-width": 2,
    }),
  );
  svg.append(group);
  $("market-chart-tooltip").textContent =
    `${dateTime(c.time)}\nO ${number(c.open)}   H ${number(c.high)}\nL ${number(c.low)}   C ${number(c.close)}`;
  $("market-chart-tooltip").classList.remove("hidden");
}
$("chart").addEventListener("pointermove", (event) => {
  if (!chartInspection) return;
  const box = $("chart").getBoundingClientRect();
  if (!box.width) return;
  const { left, right, bars, width } = chartInspection;
  const x = ((event.clientX - box.left) / box.width) * width;
  inspectStudioCandle(
    Math.round(((x - left) / (right - left)) * bars.length - 0.5),
  );
});
function closeCandleInspection() {
  $("market-chart-tooltip").classList.add("hidden");
  $("chart").querySelector("[data-inspection]")?.remove();
}
$("chart").addEventListener("pointerleave", closeCandleInspection);
$("chart").addEventListener("blur", closeCandleInspection);
$("chart").addEventListener("keydown", (event) => {
  if (!chartInspection) return;
  if (event.key === "Escape") {
    closeCandleInspection();
    return;
  }
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const last = chartInspection.bars.length - 1;
  inspectStudioCandle(
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? last
        : (chartInspection.selected ?? last) +
          (event.key === "ArrowRight" ? 1 : -1),
  );
});
let studioResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(studioResizeTimer);
  studioResizeTimer = setTimeout(() => {
    if (!current) return;
    drawChart(current.candles, current.state.position);
    paintStudioMarket();
  }, 100);
});
if (current) {
  renderStudioRunner(current);
  refreshStudioMarket();
}
setInterval(() => {
  if (!document.hidden) refreshStudioMarket();
}, 30000);
