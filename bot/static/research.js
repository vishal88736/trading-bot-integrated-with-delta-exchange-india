/* Account and research views. Credentials stay in the backend; simulations never start the runner. */
let activeView = "automation",
  accountSnapshot = null,
  accountPolling = false;
let backtestBase = null,
  backtestRunning = false,
  backtestPolling = false,
  backtestSubmitting = false,
  backtestRevision = 0;
let backtestResult = null,
  backtestPage = 0,
  backtestResultTab = "overview";
const dateTime = (value) => {
  if (value == null || value === "") return "—";
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric * (numeric > 1e14 ? 0.001 : numeric > 1e11 ? 1 : 1000))
    : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
};
function showView(view, remember = true) {
  if (!["automation", "account", "backtest"].includes(view))
    view = "automation";
  activeView = view;
  if (remember && location.hash !== `#${view}`)
    history.replaceState(null, "", `#${view}`);
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
    if (backtestResult && backtestResultTab === "overview")
      drawEquity(backtestResult.equity_curve);
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
$("account-view-paper").onclick = () => {
  showView("automation");
  if (!$("paper-position-panel").classList.contains("hidden"))
    $("paper-position-panel").scrollIntoView({
      block: "start",
      behavior: "auto",
    });
  else window.scrollTo({ top: 0, behavior: "auto" });
};

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
function renderPaperPosition(data) {
  const paper = data?.execution
    ? data.execution.simulation
    : data?.settings.mode === "paper";
  const position = paper && data.state.position;
  $("account-mode-context").classList.toggle("hidden", !paper);
  $("account-mode-title").textContent = data?.running
    ? "Paper simulation is running"
    : "Paper mode selected";
  $("paper-position-panel").classList.toggle("hidden", !position);
  if (!position) return;
  $("paper-position-status").textContent = data.running
    ? "Paper · monitoring"
    : "Paper · runner paused";
  tableRows(
    "account-paper-position",
    [position],
    [
      () => data.settings.symbol,
      (p) => (p.side === "buy" ? "Long" : "Short"),
      (p) => number(p.remaining, 0),
      (p) => number(p.entry),
      (p) => number(p.stop),
      (p) =>
        p.targets[p.stage] == null
          ? "All targets reached"
          : `TP${p.stage + 1} · ${number(p.targets[p.stage])}`,
    ],
    "No paper position.",
  );
}
function renderAccount(data) {
  accountSnapshot = data;
  const sections = data.sections || {},
    wallets = sections.balances?.rows || [];
  const positions = sections.positions?.rows || [];
  const messages = Object.entries(sections)
    .filter(([, section]) => section.error)
    .map(([name, section]) => `${name}: ${accountHelp(section.error)}`);
  if (data.error) messages.unshift(accountHelp(data.error));
  const labels = {
    disconnected:
      current?.settings.mode === "paper" && current.state.position
        ? "Your open trade is a paper simulation in Automation. Connect your Delta demo account in Connection settings to load exchange funds and holdings."
        : "Connect your demo account in Connection settings to see funds and holdings.",
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
      ? "Account connected"
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
  const positionSection = sections.positions;
  const positionsKnown = Boolean(positionSection?.updated_at);
  const positionsStale =
    positionSection?.error ||
    (positionsKnown && Date.now() / 1000 - positionSection.updated_at > 45);
  $("positions-count").textContent = positionsKnown
    ? `${positions.length}${positionsStale ? " · stale" : ""}`
    : "—";
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
    !sections.positions.error &&
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
    data.status === "disconnected"
      ? "Connect a demo account to load this information."
      : sections[name]?.error
        ? "Current data unavailable. See the connection error above."
        : sections[name]?.updated_at
          ? message
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
  const primary = [
    "symbol",
    "strategy",
    "timeframe",
    "higher_timeframe",
  ].includes(key);
  if (primary) {
    const label = {
      symbol: "Market",
      strategy: "Entry strategy",
      timeframe: "Signal timeframe",
      higher_timeframe: "Higher timeframe",
    }[key];
    copy.firstChild.textContent = label;
    if (key === "strategy")
      for (const option of input.options)
        option.textContent =
          option.value === "trend_signals"
            ? "Trend signals"
            : "Custom strategy";
  }
  $(primary ? "backtest-market-inputs" : `backtest-${section}-inputs`).append(
    copy,
  );
}
function updateBacktestSummary() {
  const value = (key) => $(`backtest-setting-${key}`).value;
  $("backtest-config-summary").textContent =
    `EMA ${value("fast_ema")} / ${value("slow_ema")} · CMO ${value("cmo_length")} · ATR ${value("atr_length")} · ${value("contracts")} contracts · ${$("backtest-fee").value} bps fee`;
  updateRiskPreview("backtest-setting-", "backtest-risk-preview");
}
function selectBacktestSettings(tab) {
  document.querySelectorAll("[data-bt-settings]").forEach((button) => {
    const active = button.dataset.btSettings === tab;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document
    .querySelectorAll("[data-bt-settings-panel]")
    .forEach((panel) =>
      panel.classList.toggle("hidden", panel.dataset.btSettingsPanel !== tab),
    );
}
function openBacktestSettings(tab = "strategy") {
  selectBacktestSettings(tab);
  $("backtest-settings-error").textContent = "";
  if (!$("backtest-settings-dialog").open)
    $("backtest-settings-dialog").showModal();
}
$("backtest-settings-open").onclick = () => openBacktestSettings();
$("backtest-settings-close").onclick = () =>
  $("backtest-settings-dialog").close();
$("backtest-settings-done").onclick = () => {
  const invalid = [
    ...$("backtest-settings-dialog").querySelectorAll("input,select"),
  ].find((input) => !input.validity.valid);
  if (invalid) {
    revealInvalidBacktestSetting(invalid);
    return;
  }
  updateBacktestSummary();
  $("backtest-settings-dialog").close();
};
function revealInvalidBacktestSetting(
  input,
  message = input.validationMessage,
) {
  const panel = input.closest("[data-bt-settings-panel]");
  if (!panel) return;
  openBacktestSettings(panel.dataset.btSettingsPanel);
  $("backtest-settings-error").textContent = message;
  input.setAttribute("aria-invalid", "true");
  input.focus();
}
$("backtest-form").addEventListener(
  "invalid",
  (event) => {
    if (event.target.closest("#backtest-settings-dialog")) {
      event.preventDefault();
      revealInvalidBacktestSetting(event.target);
    }
  },
  true,
);
$("backtest-settings-dialog").addEventListener("input", updateBacktestSummary);
$("backtest-form").addEventListener("input", (event) =>
  event.target.removeAttribute("aria-invalid"),
);
$("backtest-settings-dialog").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.matches("input")) {
    event.preventDefault();
    $("backtest-settings-done").click();
  }
});
function selectBacktestResult(tab) {
  backtestResultTab = tab;
  for (const [name, id] of [
    ["overview", "bt-overview-panel"],
    ["trades", "bt-trade-panel"],
    ["methodology", "bt-methodology-panel"],
  ])
    $(id).classList.toggle("hidden", tab !== name);
  document.querySelectorAll("[data-bt-result]").forEach((button) => {
    const active = button.dataset.btResult === tab;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (tab === "overview" && backtestResult)
    drawEquity(backtestResult.equity_curve);
}
wireTabs("[data-bt-settings]", "btSettings", selectBacktestSettings);
wireTabs("[data-bt-result]", "btResult", selectBacktestResult);
selectBacktestSettings("strategy");
selectBacktestResult("overview");
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
  updateBacktestSummary();
}
document.addEventListener("runner-status", (event) => {
  renderPaperPosition(event.detail);
  if (accountSnapshot) renderAccount(accountSnapshot);
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
      document
        .querySelectorAll(".range-presets button")
        .forEach((preset) =>
          preset.setAttribute("aria-pressed", String(preset === button)),
        );
    }),
);
for (const id of ["backtest-start", "backtest-end"])
  $(id).addEventListener("input", () =>
    document
      .querySelectorAll(".range-presets button")
      .forEach((button) => button.setAttribute("aria-pressed", "false")),
  );
$("backtest-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!backtestBase || backtestSubmitting || backtestRunning) return;
  const settings = readSettings(backtestBase, "backtest-setting-");
  const request = {
    settings,
    source: $("backtest-source").value,
    start: Math.floor(new Date($("backtest-start").value).getTime() / 1000),
    end: Math.floor(new Date($("backtest-end").value).getTime() / 1000),
    initial_balance: Number($("backtest-balance").value),
    fee_bps: Number($("backtest-fee").value),
    slippage_bps: Number($("backtest-slippage").value),
  };
  const issue = settingsIssue(settings);
  if (issue) {
    const input = $(`backtest-setting-${issue.key}`);
    showBacktestError(issue.message, input);
    return;
  }
  if (
    !Number.isFinite(request.start) ||
    !Number.isFinite(request.end) ||
    request.end <= request.start
  ) {
    showBacktestError(
      "Choose an end date after the start date.",
      $("backtest-end"),
    );
    return;
  }
  if (request.end > Date.now() / 1000) {
    showBacktestError("Choose a historical end time.", $("backtest-end"));
    return;
  }
  if (request.end - request.start > 366 * 86400) {
    showBacktestError(
      "Choose a period up to one year (366 days).",
      $("backtest-start"),
    );
    return;
  }
  if (request.end - request.start < 2 * timeframeSeconds[settings.timeframe]) {
    showBacktestError(
      "Choose a period containing at least two signal candles.",
      $("backtest-start"),
    );
    return;
  }
  if (request.slippage_bps > settings.max_entry_slippage_bps) {
    showBacktestError(
      "Test slippage exceeds the maximum entry slippage in Risk & targets.",
      $("backtest-slippage"),
    );
    return;
  }
  backtestSubmitting = true;
  backtestRevision += 1;
  updateBacktestControls();
  $("backtest-status").textContent = "Starting your backtest…";
  $("backtest-status").classList.remove("error");
  try {
    setBacktestJob(await api("backtests", request));
  } catch (error) {
    showBacktestError(error.message);
  } finally {
    backtestSubmitting = false;
    updateBacktestControls();
  }
};
function showBacktestError(message, input) {
  $("backtest-status").textContent = message;
  $("backtest-status").classList.add("error");
  if (input) {
    input.setAttribute("aria-invalid", "true");
    if (input.closest("[data-bt-settings-panel]"))
      revealInvalidBacktestSetting(input, message);
    else input.focus();
  }
}
function updateBacktestControls() {
  const busy = backtestSubmitting || backtestRunning;
  $("backtest-status").classList.toggle("is-running", busy);
  $("backtest-form").setAttribute("aria-busy", String(busy));
  for (const control of $("backtest-form").querySelectorAll(
    "input,select,button",
  ))
    control.disabled = busy;
  $("backtest-run").textContent = backtestSubmitting
    ? "Starting backtest…"
    : backtestRunning
      ? "Replaying history…"
      : "Run backtest ▶";
}
function setBacktestJob(job) {
  backtestRunning = job.status === "running";
  $("backtest-status").textContent = job.message;
  $("backtest-status").classList.toggle("error", job.status === "error");
  updateBacktestControls();
  if (backtestRunning || job.status === "error") {
    backtestResult = null;
    $("backtest-results").classList.add("hidden");
    $("bt-trade-panel").classList.add("hidden");
    $("backtest-empty").classList.remove("hidden");
    $("backtest-export").disabled = true;
    $("backtest-empty-title").textContent = backtestRunning
      ? "Your backtest is running"
      : "This test could not complete";
    $("backtest-empty-copy").textContent = backtestRunning
      ? "Fetching historical candles and replaying your strategy."
      : "Review the message above and adjust your parameters to try again.";
  }
  if (job.result) renderBacktest(job.result);
}
async function pollBacktest() {
  if (backtestPolling || backtestSubmitting) return;
  backtestPolling = true;
  const revision = backtestRevision;
  try {
    const job = await api("backtests");
    if (revision === backtestRevision) setBacktestJob(job);
  } catch {
    if (revision === backtestRevision)
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
  $("backtest-export").disabled = false;
  $("bt-result-title").textContent =
    `${result.settings.symbol} · ${result.settings.timeframe} backtest`;
  $("bt-result-source").textContent = result.source;
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
  const periodDate = (timestamp) =>
    new Date(timestamp * 1000).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  $("bt-period").textContent =
    `${periodDate(result.actual_start)} – ${periodDate(result.actual_end)} · ${result.settings.higher_timeframe} trend filter`;
  $("bt-ending").textContent =
    `Ending equity ${number(summary.ending_equity)} ${result.quote}`;
  $("bt-coverage").textContent =
    `${number(result.candles, 0)} candles · ${number(result.warmup_candles, 0)} warmup · ${number(result.ambiguous_candles, 0)} with ambiguous exit order`;
  $("bt-chart-candles").textContent =
    `${number(result.candles, 0)} historical candles`;
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
        ? check.kind === "execution_scenarios"
          ? "Bracket checks passed ✓"
          : "Metrics agree ✓"
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
    if (check.kind === "execution_scenarios") {
      const coverage = document.createElement("details");
      const title = document.createElement("summary");
      title.textContent = "What this check covers";
      const scope = document.createElement("p");
      scope.textContent = check.scope;
      coverage.append(title, scope);
      const limits = document.createElement("ul");
      for (const text of check.limitations || []) {
        const item = document.createElement("li");
        item.textContent = text;
        limits.append(item);
      }
      if (limits.childElementCount) coverage.append(limits);
      row.append(coverage);
    }
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
  selectBacktestResult("overview");
  renderTrades();
}
function drawEquity(points) {
  const svg = $("equity-chart");
  svg.replaceChildren();
  if (!points.length) return;
  const width = Math.max(320, svg.clientWidth || 800),
    height = 320;
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
        const button = document.createElement("button");
        button.type = "button";
        button.className = "bt-trade-link";
        button.textContent = "View trade ↗";
        button.onclick = () => openBacktestTrade(t);
        return button;
      },
    ],
    "No signals met these rules in the selected period. No trades were invented.",
  );
  $("bt-trade-count").textContent = `${trades.length} closed trades`;
  $("bt-trade-badge").textContent = trades.length;
  $("bt-page").textContent =
    `Page ${backtestPage + 1} of ${Math.max(1, Math.ceil(trades.length / pageSize))}`;
  $("bt-prev").disabled = backtestPage === 0;
  $("bt-next").disabled = (backtestPage + 1) * pageSize >= trades.length;
}
function openBacktestTrade(trade) {
  const quote = backtestResult.quote;
  $("bt-trade-title").textContent =
    `${backtestResult.settings.symbol} · ${trade.side === "buy" ? "Long" : "Short"}`;
  $("bt-trade-dates").textContent =
    `${dateTime(trade.entry_time)} → ${dateTime(trade.exit_time)}`;
  $("bt-trade-summary").replaceChildren();
  for (const [name, value] of [
    ["Entry", number(trade.entry)],
    ["Initial stop", number(trade.initial_stop)],
    ["Contracts", trade.quantity],
    ["Net P&L", `${number(trade.net_pnl)} ${quote}`],
    ["Trading fees", `${number(trade.fees)} ${quote}`],
  ]) {
    const group = document.createElement("div"),
      term = document.createElement("dt"),
      amount = document.createElement("dd");
    term.textContent = name;
    amount.textContent = value;
    group.append(term, amount);
    $("bt-trade-summary").append(group);
  }
  const events = [
    ...trade.exits.map((leg) => ({
      time: leg.time,
      order: leg.reason.startsWith("tp") ? Number(leg.reason.slice(2)) * 2 : 99,
      title: `${leg.reason.replaceAll("_", " ").toUpperCase()} · ${leg.quantity} contracts`,
      detail: `Filled at ${number(leg.price)} · ${number(leg.net_pnl)} ${quote} net`,
    })),
    ...trade.stop_updates.map((move) => ({
      time: move.time,
      order: move.after_target * 2 + 1,
      title: `Stop updated after TP${move.after_target}`,
      detail: `SL → ${number(move.stop)}`,
    })),
  ].sort((a, b) => a.time - b.time || a.order - b.order);
  $("bt-trade-timeline").replaceChildren();
  for (const event of events) {
    const row = document.createElement("li"),
      title = document.createElement("strong"),
      detail = document.createElement("p"),
      time = document.createElement("small");
    title.textContent = event.title;
    detail.textContent = event.detail;
    time.textContent = dateTime(event.time);
    row.append(title, detail, time);
    $("bt-trade-timeline").append(row);
  }
  $("bt-trade-dialog").showModal();
}
$("bt-trade-close").onclick = () => $("bt-trade-dialog").close();
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
  if (
    activeView === "backtest" &&
    backtestResult &&
    backtestResultTab === "overview"
  )
    drawEquity(backtestResult.equity_curve);
  if (activeView === "automation" && current)
    drawChart(current.candles, current.state.position);
});
refreshAccount();
pollBacktest();
const viewFromHash = () => location.hash.slice(1) || "automation";
showView(viewFromHash(), false);
window.addEventListener("hashchange", () => showView(viewFromHash(), false));
setInterval(refreshAccount, 5000);
setInterval(() => {
  if (backtestRunning) pollBacktest();
}, 1500);
