/* Local research controls and reports. Trading settings are never saved here. */
let researchJob = null;
let researchSelection = null;
let researchSelectionExplicit = false;
let researchDetailRevision = 0;
const researchParameters = {
  fast_ema: "Fast EMA",
  slow_ema: "Slow EMA",
  cmo_length: "CMO length",
  cmo_threshold: "CMO threshold",
  atr_length: "ATR length",
  macro_sma: "Higher-timeframe SMA",
  sl_atr: "Stop ATR multiplier",
  tp0: "TP1 ATR multiplier",
  tp1: "TP2 ATR multiplier",
  tp2: "TP3 ATR multiplier",
  ...Object.fromEntries(
    EXTRA_STRATEGY_FIELDS.filter(
      (field) =>
        field[3] === "number" && !["paper_capital_quote"].includes(field[1]),
    ).map((field) => [field[1], field[2]]),
  ),
};
for (const axis of ["x", "y"]) {
  const select = $("research-axis-" + axis);
  if (axis === "y") select.add(new Option("One parameter only", ""));
  for (const [key, label] of Object.entries(researchParameters))
    select.add(new Option(label, key));
  select.value = axis === "x" ? "fast_ema" : "sl_atr";
}
let researchAxisStrategy = null;
function updateResearchAxes() {
  updateStrategyFields("backtest-setting-");
  const name = $("backtest-setting-strategy").value;
  const preferred = {
    trend_signals: ["fast_ema", "7, 9, 12"],
    custom_strategy: ["fast_ema", "7, 9, 12"],
    momentum_breakout: ["breakout_lookback", "15, 20, 25"],
    ema_trend: ["trend_fast_period", "40, 50, 60"],
    rsi_reversion: ["rsi_length", "7, 14, 21"],
    smc_price_action: ["smc_swing_length", "10, 20, 30"],
  }[name];
  const choices = Object.entries(researchParameters).filter(([key]) => {
    const input = $("backtest-setting-" + key);
    return input && !input.parentElement.classList.contains("hidden");
  });
  for (const axis of ["x", "y"]) {
    const select = $("research-axis-" + axis),
      old = select.value;
    select.replaceChildren();
    if (axis === "y") select.add(new Option("One parameter only", ""));
    for (const [key, label] of choices) select.add(new Option(label, key));
    select.value = old;
    if (
      select.selectedIndex < 0 ||
      (axis === "x" && researchAxisStrategy !== name)
    ) {
      select.value = axis === "x" ? preferred[0] : "sl_atr";
      $("research-values-" + axis).value =
        axis === "x" ? preferred[1] : "1.5, 2, 2.5";
    }
  }
  researchAxisStrategy = name;
}
for (const key of [
  "strategy",
  "htf_filter",
  "sizing_mode",
  "smc_zone_type",
  "rsi_range_filter",
])
  $("backtest-setting-" + key).addEventListener("change", updateResearchAxes);

function updateResearchControls() {
  const mode = $("research-mode").value;
  const grid = mode === "parameters" || mode === "walk_forward";
  for (const [id, visible] of [
    ["research-coin-options", mode === "multi_coin"],
    ["research-grid-options", grid],
    ["research-validation-options", mode !== "single"],
    ["research-walk-options", mode === "walk_forward"],
  ]) {
    const panel = $(id);
    panel.classList.toggle("hidden", !visible);
    for (const control of panel.querySelectorAll("input,select"))
      control.disabled =
        backtestRunning ||
        backtestSubmitting ||
        Boolean(control.closest(".hidden"));
  }
  $("research-values-y").disabled =
    backtestRunning ||
    backtestSubmitting ||
    !grid ||
    !$("research-axis-y").value;
  $("research-cancel").classList.toggle("hidden", !backtestRunning);
  $("research-cancel").disabled = !backtestRunning;
  $("research-mode-help").textContent = {
    single:
      "Replay one strategy and inspect its trades, risk metrics, and signal checks.",
    multi_coin:
      "Compare selected markets. Missing history is reported for each coin.",
    parameters: "Compare settings on the same history. Rankings are in-sample.",
    walk_forward:
      "Select settings on earlier data, then replay untouched test folds. Training expands over time.",
  }[mode];
  $("research-mode-help").classList.toggle("hidden", mode === "single");
  if (!backtestRunning && !backtestSubmitting)
    $("backtest-run").textContent =
      mode === "single" ? "Run backtest ▶" : "Run research ▶";
}
$("research-mode").addEventListener("change", updateResearchControls);
$("research-axis-y").addEventListener("change", updateResearchControls);
updateResearchControls();

function readResearchRequest() {
  const kind = $("research-mode").value;
  const grid = {};
  if (kind === "parameters" || kind === "walk_forward") {
    for (const axis of ["x", "y"]) {
      const key = $("research-axis-" + axis).value;
      if (!key) continue;
      const input = $("research-values-" + axis);
      const parts = input.value.split(",").map((v) => v.trim());
      const values = parts.map(Number);
      if (
        parts.some((v) => !v) ||
        values.some((v) => !Number.isFinite(v)) ||
        values.length > 8 ||
        new Set(values).size !== values.length
      ) {
        input.focus();
        throw new Error(
          "Enter one to eight unique numeric values per parameter.",
        );
      }
      if (grid[key])
        throw new Error("Choose different parameters for the two axes.");
      grid[key] = values;
    }
  }
  const count = Object.values(grid).reduce(
    (total, values) => total * values.length,
    1,
  );
  const folds = Number($("research-folds").value);
  if (count > 24 || (kind === "walk_forward" && count * folds > 96))
    throw new Error(
      "Use at most 24 combinations and 96 walk-forward training runs.",
    );
  const symbols =
    kind === "multi_coin"
      ? $("research-symbols")
          .value.split(",")
          .map((v) => v.trim().toUpperCase())
      : [];
  if (
    symbols.some((v) => !/^[A-Z0-9_-]{3,60}$/.test(v)) ||
    symbols.length > 12 ||
    new Set(symbols).size !== symbols.length
  )
    throw new Error(
      "Enter up to 12 unique exchange symbols, separated by commas.",
    );
  const samples = Number($("research-lookahead").value);
  return {
    cost_stress_bps: $("backtest-stress").value
      ? $("backtest-stress").value.split(",").map(Number)
      : [],
    cache: $("research-cache").value,
    check_lookahead: samples > 0,
    lookahead_samples: samples || 16,
    research: {
      kind,
      symbols,
      grid,
      objective: $("research-objective").value,
      minimum_trades:
        kind === "single" ? 1 : Number($("research-min-trades").value),
      train_percent:
        kind === "walk_forward" ? Number($("research-train").value) : 60,
      folds: kind === "walk_forward" ? folds : 3,
    },
  };
}

function preserveResearchSelection(job) {
  return (
    researchSelectionExplicit &&
    researchJob?.run_id === job.run_id &&
    researchSelection !== (job.study?.selected_id ?? 0)
  );
}
function researchCell(row, value, tag = "td") {
  const cell = document.createElement(tag);
  cell.textContent = value;
  row.append(cell);
  return cell;
}
function returnClass(value) {
  return value == null
    ? "return-missing"
    : value > 0
      ? "return-gain"
      : value < 0
        ? "return-loss"
        : "return-flat";
}
function renderResearchAnalytics(result) {
  const data = result.analytics;
  $("research-analytics").classList.toggle("hidden", !data);
  $("research-metrics").replaceChildren();
  if (data) {
    const m = data.metrics;
    for (const [title, value, suffix] of [
      ["Daily Sharpe", m.sharpe, ""],
      ["Daily Sortino", m.sortino, ""],
      ["Calmar", m.calmar, ""],
      ["Longest drawdown", m.max_drawdown_days, " days"],
      ["Annual volatility", m.annual_volatility_percent, "%"],
      ["Complete UTC days", m.complete_days, ""],
    ]) {
      const group = document.createElement("div");
      researchCell(group, title, "dt");
      researchCell(group, value == null ? "—" : number(value) + suffix, "dd");
      $("research-metrics").append(group);
    }
    $("research-metric-method").textContent =
      "365-day crypto year; zero risk-free rate. Daily ratios exclude partial UTC days. " +
      "Trade win rate above counts closed trades. Undefined ratios are shown as —.";
    const table = document.createElement("table");
    const head = document.createElement("tr");
    researchCell(head, "Year", "th");
    for (let month = 0; month < 12; month++)
      researchCell(
        head,
        new Date(Date.UTC(2024, month, 1)).toLocaleString(undefined, {
          month: "short",
          timeZone: "UTC",
        }),
        "th",
      );
    table.append(head);
    const years = [
      ...new Set(data.monthly_returns.map((r) => r.month.slice(0, 4))),
    ];
    for (const year of years) {
      const row = document.createElement("tr");
      researchCell(row, year, "th");
      for (let month = 1; month <= 12; month++) {
        const item = data.monthly_returns.find(
          (r) => r.month === year + "-" + String(month).padStart(2, "0"),
        );
        const cell = researchCell(
          row,
          item?.return_percent == null
            ? "—"
            : number(item.return_percent) + "%" + (item.partial ? " *" : ""),
        );
        cell.className = returnClass(item?.return_percent);
      }
      table.append(row);
    }
    $("research-months").replaceChildren(table);
  }
  const check = result.lookahead_check;
  $("research-bias").textContent = check
    ? check.status.replaceAll("_", " ") +
      ": " +
      check.message +
      " " +
      (check.scope || "")
    : "No signal consistency check was recorded.";
  $("research-bias").classList.toggle(
    "error",
    ["failed", "error"].includes(check?.status),
  );
  $("research-history").replaceChildren();
  const quality = result.data_quality;
  $("research-data-quality").textContent = quality
    ? `${quality.coverage_percent}% coverage · ${number(quality.actual_candles, 0)} / ` +
      `${number(quality.expected_candles, 0)} complete signal candles. ${quality.scope} ` +
      (quality.data_sha256
        ? `Data SHA-256: ${quality.data_sha256}`
        : "Fold fingerprints are in the JSON export.")
    : "No input completeness record was saved with this result.";
  $("research-costs").replaceChildren();
  const summary = result.summary;
  for (const [label, key] of [
    ["Before-cost P&L", "before_cost_pnl"],
    ["Taker fees", "fees"],
    ["Slippage cost", "slippage_cost"],
    ["Spread cost", "spread_cost"],
  ]) {
    const group = document.createElement("div");
    researchCell(group, label, "dt");
    researchCell(
      group,
      summary[key] == null ? "—" : number(summary[key]) + " " + result.quote,
      "dd",
    );
    $("research-costs").append(group);
  }
  $("research-sample-note").textContent =
    `${summary.trades} closed positions. ` +
    (summary.trades < 100
      ? "Small sample: inspect more dates and market regimes before drawing conclusions. "
      : "Trade count alone does not establish robustness across market regimes. ") +
    "Profit factor includes costs. Before-cost P&L removes costs from these fills; it is not a separate zero-cost test.";
  const stress = result.cost_stress;
  $("research-stress-note").textContent = stress
    ? stress.status.replaceAll("_", " ") + ": " + stress.scope
    : "Cost sensitivity was not recorded. Run a new test to include it.";
  $("research-stress-results").replaceChildren();
  if (stress?.scenarios?.length) {
    const table = document.createElement("table"),
      head = document.createElement("tr");
    for (const label of [
      "Slippage per fill",
      "Return",
      "Max drawdown",
      "Positions",
      "Status",
    ])
      researchCell(head, label, "th");
    table.append(head);
    const baseline = {
      slippage_bps: result.request.slippage_bps,
      ...summary,
      status: "baseline",
    };
    for (const scenario of [baseline, ...stress.scenarios]) {
      const row = document.createElement("tr");
      researchCell(row, number(scenario.slippage_bps) + " bps");
      const cell = researchCell(
        row,
        scenario.return_percent == null
          ? "—"
          : number(scenario.return_percent) + "%",
      );
      cell.className = returnClass(scenario.return_percent);
      researchCell(
        row,
        scenario.max_drawdown_percent == null
          ? "—"
          : number(scenario.max_drawdown_percent) + "%",
      );
      researchCell(row, scenario.trades ?? "—");
      researchCell(
        row,
        scenario.message || scenario.status.replaceAll("_", " "),
      );
      table.append(row);
    }
    $("research-stress-results").append(table);
  }
  for (const item of result.history || []) {
    const li = document.createElement("li");
    li.textContent =
      item.symbol +
      " · " +
      item.resolution +
      " · " +
      item.source +
      ": " +
      (item.cached || 0).toLocaleString() +
      " cached, " +
      (item.downloaded || 0).toLocaleString() +
      " downloaded · " +
      item.policy +
      (item.oldest_fetch
        ? " · earliest fetch " + dateTime(item.oldest_fetch)
        : "");
    $("research-history").append(li);
  }
  const ready =
    researchJob?.status === "completed" && Boolean(researchJob?.run_id);
  $("research-report").disabled = !ready;
  $("research-inputs").disabled = !ready || !result.data_quality;
  $("research-quantstats").classList.toggle(
    "hidden",
    !data?.quantstats_version,
  );
  $("research-quantstats").disabled =
    !ready ||
    !data ||
    data.metrics.complete_days < 2 ||
    !data.daily_returns.some((r) => r.complete && r.return);
  $("research-quantstats").title =
    "Optional QuantStats report uses complete UTC daily returns.";
}

function renderParameterMap(study) {
  const axes = Object.keys(
    study.rows.find((row) => row.parameters)?.parameters || {},
  );
  const visible =
    study.kind === "parameters" && axes.length <= 2 && axes.length > 0;
  $("research-parameter-map").classList.toggle("hidden", !visible);
  if (!visible) return;
  const [x, y] = axes;
  const xs = [...new Set(study.rows.map((r) => r.parameters?.[x]))];
  const ys = y
    ? [...new Set(study.rows.map((r) => r.parameters?.[y]))]
    : [null];
  const table = document.createElement("table"),
    head = document.createElement("tr");
  researchCell(
    head,
    y
      ? researchParameters[y] + " / " + researchParameters[x]
      : researchParameters[x],
    "th",
  );
  for (const value of xs) researchCell(head, String(value), "th");
  table.append(head);
  for (const yvalue of ys) {
    const tr = document.createElement("tr");
    researchCell(tr, y ? String(yvalue) : "Net return", "th");
    for (const xvalue of xs) {
      const row = study.rows.find(
        (r) =>
          r.parameters?.[x] === xvalue && (!y || r.parameters?.[y] === yvalue),
      );
      const value = row?.summary?.return_percent;
      const cell = researchCell(tr, value == null ? "—" : number(value) + "%");
      cell.className = returnClass(value);
      cell.title = row?.error || row?.note || "Historical in-sample return";
    }
    table.append(tr);
  }
  $("research-heatmap").replaceChildren(table);
}

function renderResearchJob(job) {
  if (researchJob?.run_id !== job.run_id) {
    researchDetailRevision += 1;
    researchSelectionExplicit = false;
    researchSelection = job.study?.selected_id ?? 0;
  }
  researchJob = job;
  updateResearchControls();
  const study = job.study;
  $("research-study").classList.toggle("hidden", !study);
  $("backtest-downloads").classList.toggle("hidden", job.status !== "completed" || !job.result);
  $("research-report").disabled = job.status !== "completed" || !job.result;
  $("research-inputs").disabled =
    job.status !== "completed" || !job.result?.data_quality;
  $("research-quantstats").disabled = job.status !== "completed" || !job.result;
  if (!study) {
    if (job.result) renderResearchAnalytics(backtestResult || job.result);
    return;
  }
  if (!researchSelectionExplicit) researchSelection = study.selected_id;
  $("research-study").dataset.kind = study.kind;
  $("research-study-title").textContent = study.title;
  $("research-study-method").textContent =
    study.methodology + (study.note ? " " + study.note : "");
  $("research-study-count").textContent = study.rows.length + " runs recorded";
  $("research-study-rows").replaceChildren();
  for (const row of study.rows) {
    const tr = document.createElement("tr");
    const label = researchCell(tr, row.label);
    const parameters = Object.entries(row.parameters || {})
      .map(([key, value]) => (researchParameters[key] || key) + " " + value)
      .join(" · ");
    if (parameters || row.train_start) {
      const detail = document.createElement("small");
      detail.textContent =
        parameters +
        (row.train_start
          ? " · Test " +
            dateTime(row.actual_start) +
            " → " +
            dateTime(row.actual_end)
          : "");
      label.append(detail);
      if (row.train_start)
        label.title =
          "Training " +
          dateTime(row.train_start) +
          " → " +
          dateTime(row.train_end);
    }
    researchCell(
      tr,
      row.status +
        (row.eligible === false ? " · unranked" : "") +
        (row.note ? " · " + row.note : ""),
    );
    researchCell(
      tr,
      row.summary ? number(row.summary.return_percent) + "%" : "—",
    );
    researchCell(
      tr,
      row.summary ? number(row.summary.max_drawdown_percent) + "%" : "—",
    );
    researchCell(tr, row.summary?.trades ?? "—");
    researchCell(
      tr,
      row.train_summary ? number(row.train_summary.return_percent) + "%" : "—",
    );
    const cell = document.createElement("td");
    if (row.summary && job.status === "completed") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "bt-trade-link";
      button.textContent =
        researchSelection === row.id ? "Viewing" : "View run";
      button.setAttribute("aria-pressed", String(researchSelection === row.id));
      button.onclick = () => selectResearchResult(row.id);
      cell.append(button);
    } else cell.textContent = row.error || "—";
    tr.append(cell);
    $("research-study-rows").append(tr);
  }
  $("research-combined").classList.toggle(
    "hidden",
    study.kind !== "walk_forward" || job.status !== "completed",
  );
  renderParameterMap(study);
  const selected = study.rows.find((row) => row.id === researchSelection);
  if (selected && backtestResult)
    $("bt-result-title").textContent =
      backtestResult.settings.symbol +
      " · " +
      STRATEGY_NAMES[backtestResult.settings.strategy] +
      " · " +
      selected.label;
  if (backtestResult) renderResearchAnalytics(backtestResult);
}

async function selectResearchResult(index) {
  const runId = researchJob?.run_id;
  const revision = ++researchDetailRevision;
  try {
    const result = await api(
      "backtests/results/" + index + "?run_id=" + encodeURIComponent(runId),
    );
    if (revision !== researchDetailRevision || researchJob?.run_id !== runId)
      return;
    researchSelection = index;
    researchSelectionExplicit = true;
    renderBacktest(result);
    renderResearchJob(researchJob);
    $("backtest-results").scrollIntoView({ block: "start", behavior: "auto" });
  } catch (error) {
    toast(error.message);
  }
}
$("research-combined").onclick = () => selectResearchResult(0);
$("research-cancel").onclick = async () => {
  try {
    setBacktestJob(await api("backtests/cancel", {}));
  } catch (error) {
    toast(error.message);
  }
};
document.addEventListener("research-job", (event) =>
  renderResearchJob(event.detail),
);

async function downloadResearchReport(format) {
  if (!researchJob?.run_id || !backtestResult) return;
  const index = researchSelection ?? researchJob.study?.selected_id ?? 0;
  const button = $(
    format === "inputs"
      ? "research-inputs"
      : format === "html"
        ? "research-report"
        : "research-quantstats",
  );
  button.disabled = true;
  try {
    const response = await fetch(
      "/api/backtests/" +
        (format === "inputs" ? "inputs/" : "reports/") +
        index +
        "?run_id=" +
        encodeURIComponent(researchJob.run_id) +
        (format === "inputs" ? "" : "&format=" + format),
    );
    if (!response.ok)
      throw new Error((await response.json()).detail || "Report export failed");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download =
      "delta-" +
      backtestResult.settings.symbol +
      "-" +
      backtestResult.settings.strategy +
      "-" +
      format +
      (format === "inputs" ? ".json.gz" : ".html");
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    toast(error.message);
  } finally {
    if (backtestResult) renderResearchAnalytics(backtestResult);
  }
}
$("research-report").onclick = () => downloadResearchReport("html");
$("research-quantstats").onclick = () => downloadResearchReport("quantstats");
$("research-inputs").onclick = () => downloadResearchReport("inputs");
