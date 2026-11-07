/* Account and research views. Credentials stay in the backend; simulations never start the runner. */
let activeView = "automation",
  accountSnapshot = null,
  accountPolling = false;
let backtestBase = null,
  backtestRunning = false,
  backtestPolling = false;
let backtestResult = null,
  backtestPage = 0;
const dateTime = (value) => {
  if (value == null || value === "") return "—";
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric * (numeric > 1e14 ? 0.001 : numeric > 1e11 ? 1 : 1000))
    : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
};
function showView(view) {
  activeView = view;
  for (const name of ["automation", "account", "backtest"])
    $(`${name}-view`).classList.toggle("hidden", name !== view);
  for (const [name, id] of [
    ["automation", "overview-tab"],
    ["account", "account-tab"],
    ["backtest", "backtest-tab"],
  ]) {
    $(id).classList.toggle("nav-active", name === view);
    $(id).setAttribute("aria-current", name === view ? "page" : "false");
  }
  if (view === "account") refreshAccount();
  if (view === "backtest") {
    if (!backtestBase && current) copyBacktestSettings();
    if (backtestResult) drawEquity(backtestResult.equity_curve);
  }
}
$("overview-tab").onclick = () => showView("automation");
$("account-tab").onclick = () => showView("account");
$("backtest-tab").onclick = () => showView("backtest");
$("activity-tab").onclick = () => {
  showView("automation");
  $("activity").scrollIntoView({ behavior: "auto" });
};
$("account-connect").onclick = () => openSettings("connection");

function pair(top, bottom) {
  const wrapper = document.createElement("div");
  const primary = document.createElement("span");
  primary.textContent = top ?? "—";
  wrapper.append(primary);
  if (bottom != null) {
    const secondary = document.createElement("small");
    secondary.textContent = bottom;
    wrapper.append(secondary);
  }
  return wrapper;
}
function tableRows(id, rows, columns, empty) {
  const body = $(id);
  body.replaceChildren();
  if (!rows.length) {
    const row = document.createElement("tr"),
      cell = document.createElement("td");
    cell.colSpan = columns.length;
    cell.className = "table-empty";
    cell.textContent = empty;
    row.append(cell);
    body.append(row);
    return;
  }
  for (const value of rows) {
    const row = document.createElement("tr");
    for (const column of columns) {
      const cell = document.createElement("td"),
        content = column(value);
      if (content instanceof Node) cell.append(content);
      else cell.textContent = content ?? "—";
      row.append(cell);
    }
    body.append(row);
  }
}
const accountHelp = (message) => {
  if (/ip_not|whitelist/i.test(message))
    return `${message}. Update the demo key's IP whitelist for the computer running this bot.`;
  if (/invalid_api_key|invalid_signature|Signature/i.test(message))
    return `${message}. Check the demo key/secret and automatic system time.`;
  if (/UnauthorizedApiAccess|permission/i.test(message))
    return `${message}. Check the API key's account read permissions.`;
  return message;
};
function renderAccount(data) {
  accountSnapshot = data;
  const sections = data.sections || {},
    wallets = sections.balances?.rows || [];
  const positions = sections.positions?.rows || [];
  const messages = Object.entries(sections)
    .filter(([, section]) => section.error)
    .map(([name, section]) => `${name}: ${accountHelp(section.error)}`);
  const labels = {
    disconnected: "Connect your demo account to see funds and holdings.",
    loading: "Fetching account information from Delta demo…",
    connected:
      "Connected to Delta India demo. Account data refreshes automatically, even while the runner is paused.",
    partial:
      "Some account data could not be refreshed. Previous values below are marked stale.",
    error:
      "Account information could not be loaded. Check the connection settings and try again.",
  };
  $("connection-label").textContent =
    data.status === "connected"
      ? "Demo account connected"
      : data.status === "disconnected"
        ? "Connect demo account"
        : data.status === "loading"
          ? "Connecting account…"
          : "Demo connection needs attention";
  $("connection-button")
    .querySelector(".dot")
    .classList.toggle("gray", data.status !== "connected");
  $("account-notice").textContent =
    `${labels[data.status]} ${messages.join(" ")}`;
  $("account-notice").classList.toggle("error", messages.length > 0);
  $("connection-result").textContent =
    `${labels[data.status]} ${messages.join(" ")}`;
  const accountId = wallets.find((w) => w.account_id != null)?.account_id;
  $("account-identity").textContent =
    `Delta India · Demo${accountId != null ? ` · Account ${accountId}` : ""}`;
  const assets = wallets.map((w) => w.asset).filter(Boolean);
  if (
    JSON.stringify(assets) !==
    JSON.stringify([...$("account-asset").options].map((o) => o.value))
  ) {
    const previous = $("account-asset").value;
    $("account-asset").replaceChildren();
    for (const symbol of assets) {
      const option = document.createElement("option");
      option.value = option.textContent = symbol;
      $("account-asset").append(option);
    }
    if (assets.includes(previous)) $("account-asset").value = previous;
    else if (assets.includes(current?.quote))
      $("account-asset").value = current.quote;
    else if (wallets.some((w) => w.balance))
      $("account-asset").value = wallets.find((w) => w.balance).asset;
  }
  const selected = $("account-asset").value,
    wallet = wallets.find((w) => w.asset === selected);
  const amount = (value) =>
    value == null ? "—" : `${number(value)} ${selected}`;
  $("account-balance").textContent = amount(wallet?.balance);
  $("account-available").textContent = amount(wallet?.available_balance);
  $("account-blocked").textContent = amount(wallet?.blocked_margin);
  const relevant = positions.filter((p) => p.asset === selected);
  const pnlKnown =
    sections.positions?.updated_at &&
    selected &&
    !positions.some((p) => p.asset == null) &&
    relevant.every((p) => p.unrealized_pnl != null);
  const pnl = pnlKnown
    ? relevant.reduce((sum, p) => sum + p.unrealized_pnl, 0)
    : null;
  $("account-unrealized").textContent = amount(pnl);
  $("account-unrealized").classList.toggle("positive", pnl > 0);
  $("account-unrealized").classList.toggle("negative", pnl < 0);
  $("account-updated").textContent = sections.balances?.updated_at
    ? `Wallet fetched ${dateTime(sections.balances.updated_at)}${data.refreshing ? " · refreshing…" : ""}`
    : data.refreshing
      ? "Fetching from exchange…"
      : "No exchange snapshot yet";
  for (const name of ["balances", "positions", "orders", "fills"]) {
    const section = sections[name],
      stale =
        section?.error ||
        (section?.updated_at && Date.now() / 1000 - section.updated_at > 45);
    $(`${name}-freshness`).textContent = section?.updated_at
      ? `${stale ? "Stale · " : ""}${dateTime(section.updated_at)}`
      : section?.error
        ? "Fetch failed"
        : "Not fetched";
    $(`${name}-freshness`).classList.toggle(
      "negative",
      Boolean(stale || section?.error),
    );
  }
  const empty = (name, message) =>
    sections[name]?.updated_at
      ? message
      : data.status === "disconnected"
        ? "Connect a demo account to load this information."
        : sections[name]?.error
          ? "Data unavailable. See the connection error above."
          : "Waiting for exchange data…";
  tableRows(
    "account-balances",
    wallets,
    [
      (w) => w.asset,
      ...[
        "balance",
        "available_balance",
        "blocked_margin",
        "position_margin",
        "order_margin",
        "cross_position_margin",
        "cross_order_margin",
        "portfolio_margin",
      ].map((key) => (w) => number(w[key], 4)),
    ],
    empty("balances", "The exchange returned no wallets."),
  );
  tableRows(
    "account-positions",
    positions,
    [
      (p) => p.symbol,
      (p) => (p.size == null ? "—" : p.size > 0 ? "Long" : "Short"),
      (p) => (p.size == null ? "—" : number(Math.abs(p.size), 0)),
      (p) => number(p.entry_price),
      (p) => number(p.mark_price),
      (p) => pair(number(p.margin), p.asset),
      (p) => pair(number(p.unrealized_pnl), p.asset),
      (p) => number(p.liquidation_price),
      (p) => p.margin_mode,
    ],
    empty("positions", "No open positions in this demo account."),
  );
  const orders = sections.orders?.rows || [];
  $("orders-count").textContent =
    `${sections.orders?.truncated ? "First " : ""}${orders.length} orders${sections.orders?.truncated ? " · additional orders exist at Delta" : " · all products"}`;
  tableRows(
    "account-orders",
    orders,
    [
      (o) => pair(o.symbol, o.id),
      (o) => pair(o.side, o.order_type?.replaceAll("_", " ")),
      (o) => number(o.unfilled_size, 0),
      (o) =>
        pair(
          number(o.limit_price),
          o.stop_price ? `Trigger ${number(o.stop_price)}` : null,
        ),
      (o) => pair(o.state, o.reduce_only ? "Reduce only" : null),
    ],
    empty("orders", "No open or pending orders."),
  );
  tableRows(
    "account-fills",
    sections.fills?.rows || [],
    [
      (f) => pair(f.symbol, dateTime(f.created_at)),
      (f) => f.side,
      (f) => number(f.size, 0),
      (f) => number(f.price),
      (f) => pair(number(f.commission, 4), f.asset),
    ],
    empty("fills", "No recent fills returned by Delta."),
  );
  $("account-refresh").disabled = data.refreshing;
  $("account-refresh").textContent = data.refreshing
    ? "Refreshing…"
    : "Refresh account ↻";
}
async function refreshAccount(force = false) {
  if (accountPolling) return;
  accountPolling = true;
  try {
    renderAccount(
      await api(force ? "account/refresh" : "account", force ? {} : undefined),
    );
  } catch {
    $("account-notice").textContent =
      "Dashboard connection lost. Account values may be stale; retrying automatically.";
    $("account-notice").classList.add("error");
  } finally {
    accountPolling = false;
  }
}
$("account-refresh").onclick = () => refreshAccount(true);
$("account-asset").onchange = () => renderAccount(accountSnapshot);
$("test-connection").onclick = () => refreshAccount(true);
document.addEventListener("credentials-saved", () => refreshAccount(true));

for (const [section, key] of fields) {
  if (["mode", "poll_seconds", "paper_fee_bps"].includes(key)) continue;
  const copy = $(`setting-${key}`).parentElement.cloneNode(true);
  const input = copy.querySelector("input,select");
  input.id = `backtest-setting-${key}`;
  input.name = `backtest-${key}`;
  $(`backtest-${section}-inputs`).append(copy);
}
function copyBacktestSettings() {
  if (!current) return;
  backtestBase = structuredClone(current.settings);
  for (const [, key] of fields) {
    const input = $(`backtest-setting-${key}`);
    if (!input) continue;
    input.value = key.startsWith("tp")
      ? backtestBase.tp_atr[Number(key[2])]
      : backtestBase[key];
  }
}
document.addEventListener("runner-status", () => {
  if (!backtestBase) copyBacktestSettings();
});
$("backtest-copy").onclick = () => {
  copyBacktestSettings();
  toast("Runner settings copied into this backtest.");
};
const localInput = (date) =>
  new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
$("backtest-end").value = localInput(new Date());
$("backtest-start").value = localInput(new Date(Date.now() - 7 * 86400000));
document.querySelectorAll(".range-presets button").forEach(
  (button) =>
    (button.onclick = () => {
      const end = new Date(),
        start = new Date(end);
      if (Number(button.dataset.days) === 365)
        start.setFullYear(start.getFullYear() - 1);
      else start.setDate(start.getDate() - Number(button.dataset.days));
      $("backtest-start").value = localInput(start);
      $("backtest-end").value = localInput(end);
    }),
);
$("backtest-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!backtestBase) return;
  const settings = structuredClone(backtestBase);
  for (const [, key, , kind] of fields) {
    const input = $(`backtest-setting-${key}`);
    if (!input) continue;
    const value = kind === "number" ? Number(input.value) : input.value;
    if (key.startsWith("tp")) settings.tp_atr[Number(key[2])] = value;
    else settings[key] = value;
  }
  const request = {
    settings,
    source: $("backtest-source").value,
    start: Math.floor(new Date($("backtest-start").value).getTime() / 1000),
    end: Math.floor(new Date($("backtest-end").value).getTime() / 1000),
    initial_balance: Number($("backtest-balance").value),
    fee_bps: Number($("backtest-fee").value),
    slippage_bps: Number($("backtest-slippage").value),
  };
  try {
    setBacktestJob(await api("backtests", request));
  } catch (error) {
    $("backtest-status").textContent = error.message;
    $("backtest-status").classList.add("error");
  }
};
function setBacktestJob(job) {
  backtestRunning = job.status === "running";
  $("backtest-status").textContent = job.message;
  $("backtest-status").classList.toggle("error", job.status === "error");
  for (const control of $("backtest-form").querySelectorAll(
    "input,select,button",
  ))
    control.disabled = backtestRunning;
  $("backtest-run").textContent = backtestRunning
    ? "Replaying history…"
    : "Run backtest ▶";
  if (backtestRunning || job.status === "error") {
    backtestResult = null;
    $("backtest-results").classList.add("hidden");
    $("bt-trade-panel").classList.add("hidden");
    $("backtest-empty").classList.remove("hidden");
    $("backtest-export").disabled = true;
  }
  if (job.result) renderBacktest(job.result);
}
async function pollBacktest() {
  if (backtestPolling) return;
  backtestPolling = true;
  try {
    setBacktestJob(await api("backtests"));
  } catch {
    $("backtest-status").textContent =
      "Lost connection to the replay. Reconnecting…";
  } finally {
    backtestPolling = false;
  }
}
function renderBacktest(result) {
  backtestResult = result;
  backtestPage = 0;
  $("backtest-results").classList.remove("hidden");
  $("backtest-empty").classList.add("hidden");
  $("bt-trade-panel").classList.remove("hidden");
  $("backtest-export").disabled = false;
  const summary = result.summary;
  $("bt-pnl").textContent = `${number(summary.net_pnl)} ${result.quote}`;
  $("bt-pnl").className = summary.net_pnl >= 0 ? "positive" : "negative";
  $("bt-return").textContent =
    `${number(summary.return_percent)}% return after fees`;
  $("bt-trades").textContent = summary.trades;
  $("bt-wins").textContent =
    `${summary.win_rate == null ? "—" : `${number(summary.win_rate, 1)}%`} win rate`;
  $("bt-drawdown").textContent = `${number(summary.max_drawdown_percent)}%`;
  $("bt-fees").textContent = `${number(summary.fees)} ${result.quote}`;
  $("bt-factor").textContent =
    `Profit factor: ${summary.profit_factor == null ? (summary.trades && summary.gross_profit > 0 ? "No losing trades" : "—") : number(summary.profit_factor)}`;
  $("bt-period").textContent =
    `${result.settings.symbol} · ${result.settings.timeframe} / ${result.settings.higher_timeframe} · ${dateTime(result.actual_start)} to ${dateTime(result.actual_end)} · ${result.source}`;
  $("bt-ending").textContent =
    `Ending equity ${number(summary.ending_equity)} ${result.quote}`;
  $("bt-coverage").textContent =
    `${result.candles} test candles · ${result.warmup_candles} earlier warmup candles · ${result.ambiguous_candles} candles with ambiguous exit order`;
  $("bt-reference-checks").replaceChildren();
  for (const check of result.reference_checks || []) {
    const row = document.createElement("div");
    row.className = "reference-check";
    const name = document.createElement("a");
    name.href = check.url;
    name.target = "_blank";
    name.rel = "noopener noreferrer";
    name.textContent = check.name;
    const status = document.createElement("strong");
    status.textContent =
      check.status === "passed"
        ? "Metrics agree ✓"
        : check.status.replaceAll("_", " ");
    status.className = check.status === "passed" ? "positive" : "negative";
    const detail = document.createElement("p");
    detail.textContent =
      check.message ||
      Object.entries(check.checks || {})
        .map(
          ([metric, value]) =>
            `${metric.replaceAll("_", " ")}: ${value.passed ? "agrees" : "mismatch"}`,
        )
        .join(" · ");
    row.append(name, status, detail);
    $("bt-reference-checks").append(row);
  }
  $("bt-assumptions").replaceChildren();
  for (const text of result.assumptions) {
    const li = document.createElement("li");
    li.textContent = text;
    $("bt-assumptions").append(li);
  }
  const rejected = Object.entries(result.rejected_entries);
  $("bt-rejections").textContent = rejected.length
    ? `Skipped entries: ${rejected.map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join("; ")}`
    : "No entries were rejected by the configured limits.";
  drawEquity(result.equity_curve);
  renderTrades();
}
function drawEquity(points) {
  const svg = $("equity-chart");
  svg.replaceChildren();
  if (!points.length) return;
  const width = Math.max(320, svg.clientWidth || 800),
    height = 285;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const left = 80,
    right = width - 18,
    top = 18,
    bottom = height - 45;
  let low = Infinity,
    high = -Infinity;
  for (const point of points) {
    low = Math.min(low, point.equity);
    high = Math.max(high, point.equity);
  }
  const pad = (high - low) * 0.1 || Math.max(1, high * 0.001);
  low -= pad;
  high += pad;
  const y = (value) => bottom - ((value - low) / (high - low)) * (bottom - top);
  const x = (index) =>
    left + (index / Math.max(points.length - 1, 1)) * (right - left);
  for (let i = 0; i < 4; i++) {
    const value = low + ((high - low) * i) / 3,
      cy = y(value);
    svg.append(
      svgNode("line", {
        x1: left,
        x2: right,
        y1: cy,
        y2: cy,
        stroke: "#e4eae5",
      }),
      svgNode(
        "text",
        {
          x: left - 10,
          y: cy + 4,
          fill: "#4b5e53",
          "font-size": 12,
          "text-anchor": "end",
        },
        number(value),
      ),
    );
  }
  // Keep the graph bounded in size while preserving the complete curve in the download.
  const stride = Math.max(1, Math.floor(points.length / 1500));
  const sampled = points
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => i % stride === 0 || i === points.length - 1);
  svg.append(
    svgNode("polyline", {
      points: sampled.map(({ p, i }) => `${x(i)},${y(p.equity)}`).join(" "),
      fill: "none",
      stroke: "#267451",
      "stroke-width": 2,
    }),
  );
  for (const index of [
    0,
    Math.floor((points.length - 1) / 2),
    points.length - 1,
  ])
    svg.append(
      svgNode(
        "text",
        {
          x: x(index),
          y: height - 13,
          fill: "#4b5e53",
          "font-size": 12,
          "text-anchor":
            index === 0
              ? "start"
              : index === points.length - 1
                ? "end"
                : "middle",
        },
        new Date(points[index].time * 1000).toLocaleDateString(),
      ),
    );
}
function renderTrades() {
  const trades = backtestResult?.trades || [],
    pageSize = 20;
  tableRows(
    "bt-trade-rows",
    trades.slice(backtestPage * pageSize, (backtestPage + 1) * pageSize),
    [
      (t) => dateTime(t.entry_time),
      (t) => (t.side === "buy" ? "Long" : "Short"),
      (t) => pair(number(t.entry), `SL ${number(t.initial_stop)}`),
      (t) => t.quantity,
      (t) => number(t.net_pnl),
      (t) => pair(t.final_reason.replaceAll("_", " "), dateTime(t.exit_time)),
      (t) => {
        const details = document.createElement("details"),
          summary = document.createElement("summary");
        summary.textContent = "Exits & stop updates";
        details.append(summary);
        const exits = document.createElement("ul");
        for (const leg of t.exits) {
          const li = document.createElement("li");
          li.textContent = `${dateTime(leg.time)} · ${leg.reason.replaceAll("_", " ")} · ${leg.quantity} @ ${number(leg.price)}`;
          exits.append(li);
        }
        for (const move of t.stop_updates) {
          const li = document.createElement("li");
          li.textContent = `After TP${move.after_target}: SL → ${number(move.stop)}`;
          exits.append(li);
        }
        details.append(exits);
        return details;
      },
    ],
    "No signals met these rules in the selected period. No trades were invented.",
  );
  $("bt-trade-count").textContent = `${trades.length} closed trades`;
  $("bt-page").textContent =
    `Page ${backtestPage + 1} of ${Math.max(1, Math.ceil(trades.length / pageSize))}`;
  $("bt-prev").disabled = backtestPage === 0;
  $("bt-next").disabled = (backtestPage + 1) * pageSize >= trades.length;
}
$("bt-prev").onclick = () => {
  backtestPage--;
  renderTrades();
};
$("bt-next").onclick = () => {
  backtestPage++;
  renderTrades();
};
$("backtest-export").onclick = () => {
  if (!backtestResult) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(backtestResult, null, 2)], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `delta-backtest-${backtestResult.settings.symbol}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
};
window.addEventListener("resize", () => {
  if (activeView === "backtest" && backtestResult)
    drawEquity(backtestResult.equity_curve);
  if (activeView === "automation" && current)
    drawChart(current.candles, current.state.position);
});
refreshAccount();
pollBacktest();
setInterval(refreshAccount, 5000);
setInterval(() => {
  if (backtestRunning) pollBacktest();
}, 1500);
