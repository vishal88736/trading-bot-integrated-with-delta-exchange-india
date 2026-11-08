import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { JSDOM } from "jsdom";

const settings = {
  mode: "paper",
  symbol: "BTCUSD",
  timeframe: "5m",
  higher_timeframe: "1h",
  strategy: "trend_signals",
  fast_ema: 9,
  slow_ema: 21,
  cmo_length: 14,
  cmo_threshold: 0,
  atr_length: 14,
  macro_sma: 200,
  sl_atr: 2,
  tp_atr: [1, 2, 4],
  contracts: 4,
  leverage: 1,
  max_contracts: 4,
  max_notional_quote: 1000,
  max_loss_quote: 50,
  max_entry_slippage_bps: 30,
  paper_fee_bps: 5,
  poll_seconds: 5,
};
const initial = {
  running: false,
  error: null,
  settings,
  state: { position: null, pending: null, realized_quote: 12, events: [] },
  quote: "USD",
  price: null,
  candles: [],
  credentials_configured: false,
};
const ready = {
  status: "connected",
  refreshing: false,
  sections: {
    balances: {
      updated_at: 1700000000,
      error: null,
      rows: [
        {
          asset: "USD",
          account_id: 11,
          balance: 1000,
          available_balance: 850,
          blocked_margin: 150,
        },
        { asset: "BTC", balance: 0.1, available_balance: 0.1 },
      ],
    },
    positions: {
      updated_at: 1700000000,
      error: null,
      rows: [{ symbol: "BTCUSD", size: 4, unrealized_pnl: -4, asset: "USD" }],
    },
    orders: { updated_at: 1700000000, rows: [] },
    fills: { updated_at: 1700000000, rows: [] },
  },
};
async function settle() {
  for (let i = 0; i < 4; i++)
    await new Promise((resolve) => setImmediate(resolve));
}
async function dashboard(t, account = ready, status = initial, hash = "") {
  const css = readFileSync("bot/static/style.css", "utf8");
  const html = readFileSync("bot/static/index.html", "utf8").replace(
    "</head>",
    `<style>${css}</style></head>`,
  );
  const dom = new JSDOM(html, {
    url: `http://127.0.0.1:8001/${hash}`,
    runScripts: "outside-only",
  });
  t.after(() => dom.window.close());
  const calls = [],
    state = structuredClone(status),
    w = dom.window;
  w.structuredClone = structuredClone;
  w.matchMedia = () => ({ matches: true });
  w.scrollTo = () => {};
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  w.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  w.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ url, body });
    let data;
    if (url === "/api/status") data = state;
    else if (url.startsWith("/api/account")) data = account;
    else if (url === "/api/backtests")
      data = body
        ? { status: "running", message: "Loading history", result: null }
        : { status: "idle", message: "Choose a range", result: null };
    else if (url === "/api/settings") {
      state.settings = body;
      data = { saved: true };
    } else data = { saved: true };
    return { ok: true, json: async () => structuredClone(data) };
  };
  for (const file of ["app.js", "research.js"])
    new vm.Script(readFileSync(`bot/static/${file}`, "utf8"), {
      filename: file,
    }).runInContext(dom.getInternalVMContext());
  await settle();
  return { w, document: w.document, calls, state };
}

test("navigation restores the selected page from the URL", async (t) => {
  const { w, document: d } = await dashboard(t, ready, initial, "#backtest");
  assert.equal(
    d.getElementById("backtest-view").classList.contains("hidden"),
    false,
  );
  d.getElementById("account-tab").click();
  assert.equal(w.location.hash, "#account");
  const restored = await dashboard(t, ready, initial, w.location.hash);
  assert.equal(
    restored.document
      .getElementById("account-view")
      .classList.contains("hidden"),
    false,
  );
  assert.equal(
    restored.document
      .getElementById("account-tab")
      .getAttribute("aria-current"),
    "page",
  );
});

test("settings tabs support keyboard navigation and reveal invalid hidden fields", async (t) => {
  const { w, document: d } = await dashboard(t);
  w.openSettings();
  d.getElementById("settings-strategy-tab").dispatchEvent(
    new w.KeyboardEvent("keydown", { key: "ArrowRight" }),
  );
  assert.equal(
    d.getElementById("settings-risk-tab").getAttribute("aria-selected"),
    "true",
  );
  assert.equal(d.activeElement.id, "settings-risk-tab");
  const input = d.getElementById("setting-fast_ema");
  input.value = "0";
  input.dispatchEvent(new w.Event("invalid", { cancelable: true }));
  assert.equal(
    d.getElementById("settings-strategy-tab").getAttribute("aria-selected"),
    "true",
  );
  assert.equal(d.activeElement, input);
  assert.equal(input.getAttribute("aria-invalid"), "true");
  assert.ok(d.getElementById("form-error").textContent.length > 0);
});

test("risk previews update while editing without saving runner settings", async (t) => {
  const { w, document: d, calls, state } = await dashboard(t);
  w.openSettings("risk");
  for (const [key, value] of [
    ["contracts", 7],
    ["tp0", 2],
    ["tp1", 4],
    ["tp2", 6],
  ]) {
    const input = d.getElementById(`setting-${key}`);
    input.value = value;
    input.dispatchEvent(new w.Event("input", { bubbles: true }));
  }
  assert.match(
    d.getElementById("ratio-note").textContent,
    /1.00R \/ 2.00R \/ 3.00R/,
  );
  assert.match(
    d.getElementById("ratio-note").textContent,
    /3 \/ 1 \/ 3 contracts/,
  );
  const contracts = d.getElementById("backtest-setting-contracts");
  contracts.value = "7";
  contracts.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.match(
    d.getElementById("backtest-risk-preview").textContent,
    /3 \/ 1 \/ 3 contracts/,
  );
  assert.equal(state.settings.contracts, 4);
  assert.ok(!calls.some((c) => c.url === "/api/settings"));
});

test("lowercase market symbols normalize in settings and backtest submissions", async (t) => {
  const { w, document: d, calls } = await dashboard(t);
  w.openSettings();
  d.getElementById("setting-symbol").value = " ethusd ";
  d.getElementById("settings-form").dispatchEvent(
    new w.Event("submit", { cancelable: true }),
  );
  await settle();
  assert.equal(
    calls.find((c) => c.url === "/api/settings").body.symbol,
    "ETHUSD",
  );
  d.getElementById("backtest-setting-symbol").value = " btcusd ";
  d.getElementById("backtest-form").dispatchEvent(
    new w.Event("submit", { cancelable: true }),
  );
  await settle();
  assert.equal(
    calls.find((c) => c.url === "/api/backtests" && c.body).body.settings
      .symbol,
    "BTCUSD",
  );
});

test("invalid target order opens the risk tab before submitting any settings", async (t) => {
  const { w, document: d, calls } = await dashboard(t);
  w.openSettings();
  d.getElementById("setting-tp0").value = "3";
  d.getElementById("settings-form").dispatchEvent(
    new w.Event("submit", { cancelable: true }),
  );
  assert.equal(
    d.getElementById("settings-risk-tab").getAttribute("aria-selected"),
    "true",
  );
  assert.equal(d.activeElement.id, "setting-tp0");
  assert.match(d.getElementById("form-error").textContent, /increasing order/);
  assert.ok(!calls.some((c) => c.url === "/api/settings"));
});

test("connection form Enter saves credentials rather than strategy settings", async (t) => {
  const { w, document: d, calls } = await dashboard(t);
  w.openSettings("connection");
  d.getElementById("api-key").value = "fixture-key";
  d.getElementById("api-secret").value = "fixture-secret";
  d.getElementById("setting-fast_ema").value = "0";
  d.getElementById("api-secret").dispatchEvent(
    new w.KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    }),
  );
  await settle();
  assert.equal(calls.filter((c) => c.url === "/api/credentials").length, 1);
  assert.ok(!calls.some((c) => c.url === "/api/settings"));
  assert.equal(d.getElementById("api-key").value, "");
  assert.equal(d.getElementById("api-secret").value, "");
});

test("backtest submission disables controls immediately and prevents duplicate requests", async (t) => {
  const { w, document: d } = await dashboard(t);
  const original = w.fetch;
  let release,
    posts = 0;
  w.fetch = (url, options) => {
    if (url === "/api/backtests" && options?.method === "POST") {
      posts += 1;
      return new Promise((resolve) => {
        release = resolve;
      });
    }
    return original(url, options);
  };
  const submit = () =>
    d
      .getElementById("backtest-form")
      .dispatchEvent(new w.Event("submit", { cancelable: true }));
  submit();
  submit();
  assert.equal(posts, 1);
  assert.equal(d.getElementById("backtest-run").disabled, true);
  assert.match(
    d.getElementById("backtest-run").textContent,
    /Starting backtest/,
  );
  release({
    ok: true,
    json: async () => ({ status: "running", message: "Loading history" }),
  });
  await settle();
  assert.match(d.getElementById("backtest-run").textContent, /Replaying/);
  w.setBacktestJob({ status: "error", message: "Incomplete history" });
  assert.equal(d.getElementById("backtest-run").disabled, false);
});

test("an old status response cannot unlock a newly started backtest", async (t) => {
  const { w, document: d } = await dashboard(t);
  const original = w.fetch;
  let release;
  w.fetch = (url, options) =>
    url === "/api/backtests" && !options?.method
      ? new Promise((resolve) => {
          release = resolve;
        })
      : original(url, options);
  const stale = w.pollBacktest();
  d.getElementById("backtest-form").dispatchEvent(
    new w.Event("submit", { cancelable: true }),
  );
  await settle();
  release({
    ok: true,
    json: async () => ({ status: "idle", message: "Old snapshot" }),
  });
  await stale;
  assert.equal(d.getElementById("backtest-run").disabled, true);
  assert.match(d.getElementById("backtest-run").textContent, /Replaying/);
});

test("backtest date errors focus the field without starting a job", async (t) => {
  const { w, document: d, calls } = await dashboard(t);
  d.getElementById("backtest-tab").click();
  d.getElementById("backtest-end").value =
    d.getElementById("backtest-start").value;
  d.getElementById("backtest-form").dispatchEvent(
    new w.Event("submit", { cancelable: true }),
  );
  assert.match(
    d.getElementById("backtest-status").textContent,
    /end date after the start/,
  );
  assert.equal(d.activeElement.id, "backtest-end");
  assert.ok(!calls.some((c) => c.url === "/api/backtests" && c.body));
});

test("account navigation shows actual exchange wallet assets separately from bot P&L", async (t) => {
  const { document: d } = await dashboard(t);
  d.getElementById("account-tab").click();
  assert.equal(
    d.getElementById("account-view").classList.contains("hidden"),
    false,
  );
  assert.equal(
    d.getElementById("automation-view").classList.contains("hidden"),
    true,
  );
  assert.match(d.getElementById("account-balance").textContent, /1,000.00 USD/);
  assert.match(d.getElementById("account-unrealized").textContent, /-4.00 USD/);
  assert.match(d.getElementById("pnl-value").textContent, /12.00/);
  d.getElementById("account-asset").value = "BTC";
  d.getElementById("account-asset").dispatchEvent(
    new d.defaultView.Event("change"),
  );
  assert.match(d.getElementById("account-balance").textContent, /0.10 BTC/);
});

test("disconnected account shows no fabricated zero balances", async (t) => {
  const { document: d } = await dashboard(t, {
    status: "disconnected",
    refreshing: false,
    sections: {},
  });
  assert.equal(d.getElementById("account-balance").textContent, "—");
  assert.match(
    d.getElementById("account-balances").textContent,
    /Connect a demo account/,
  );
});

test("Account links to a paused paper simulation in Automation without inventing exchange holdings", async (t) => {
  const status = structuredClone(initial);
  status.settings.symbol = "ETHUSD";
  status.state.position = {
    side: "buy",
    entry: 2000,
    stop: 2000,
    targets: [2010, 2020, 2040],
    quantities: [2, 1, 1],
    remaining: 2,
    stage: 1,
  };
  const {
    w,
    document: d,
    state,
    calls,
  } = await dashboard(
    t,
    { status: "disconnected", refreshing: false, sections: {} },
    status,
  );
  d.getElementById("account-tab").click();
  assert.equal(
    d
      .getElementById("account-view")
      .contains(d.getElementById("paper-position-panel")),
    false,
  );
  assert.equal(
    d
      .getElementById("automation-view")
      .contains(d.getElementById("paper-position-panel")),
    true,
  );
  assert.equal(
    d.getElementById("execution-mode-label").textContent,
    "Paper mode",
  );
  d.getElementById("account-view-paper").click();
  assert.equal(
    d.getElementById("automation-view").classList.contains("hidden"),
    false,
  );
  assert.equal(
    d.getElementById("paper-position-panel").classList.contains("hidden"),
    false,
  );
  assert.match(
    d.getElementById("account-paper-position").textContent,
    /ETHUSD/,
  );
  assert.match(
    d.getElementById("account-paper-position").textContent,
    /TP2 · 2,020.00/,
  );
  assert.match(
    d.getElementById("paper-position-status").textContent,
    /runner paused/,
  );
  assert.match(d.getElementById("status-value").textContent, /Paused/);
  assert.match(
    d.getElementById("start-button").textContent,
    /Resume paper run/,
  );
  assert.match(
    d.getElementById("account-notice").textContent,
    /paper simulation in Automation/,
  );
  assert.equal(d.getElementById("account-balance").textContent, "—");
  assert.doesNotMatch(
    d.getElementById("account-positions").textContent,
    /ETHUSD/,
  );
  state.state.position = null;
  w.render(state);
  assert.equal(
    d.getElementById("paper-position-panel").classList.contains("hidden"),
    true,
  );
  assert.ok(
    !calls.some((c) =>
      ["/api/start", "/api/stop", "/api/settings", "/api/reconcile"].includes(
        c.url,
      ),
    ),
  );
});

test("a connected demo account does not turn a running paper trade into an exchange position", async (t) => {
  const status = structuredClone(initial);
  status.settings.symbol = "ETHUSD";
  status.running = true;
  status.credentials_configured = true;
  status.state.position = {
    side: "sell",
    entry: 2000,
    stop: 2020,
    targets: [1990, 1980, 1960],
    quantities: [2, 1, 1],
    remaining: 4,
    stage: 0,
  };
  const account = structuredClone(ready);
  account.sections.positions.rows = [];
  account.sections.positions.updated_at = Math.floor(Date.now() / 1000);
  const {
    w,
    document: d,
    calls,
    state,
  } = await dashboard(t, account, status, "#account");
  assert.equal(
    d.getElementById("execution-mode-label").textContent,
    "Paper mode",
  );
  assert.equal(
    d.getElementById("connection-label").textContent,
    "Account connected",
  );
  assert.equal(d.getElementById("positions-count").textContent, "0");
  assert.match(
    d.getElementById("account-mode-context").textContent,
    /does not switch the bot/,
  );
  assert.doesNotMatch(d.getElementById("account-view").textContent, /ETHUSD/);
  assert.match(
    d.getElementById("account-paper-position").textContent,
    /ETHUSD/,
  );
  d.getElementById("execution-mode-button").click();
  assert.equal(d.getElementById("setting-mode").value, "paper");
  assert.equal(state.settings.mode, "paper");
  assert.ok(
    !calls.some((c) =>
      ["/api/start", "/api/stop", "/api/settings", "/api/reconcile"].includes(
        c.url,
      ),
    ),
  );
  state.settings.mode = "demo";
  w.render(state);
  assert.equal(
    d.getElementById("execution-mode-label").textContent,
    "Demo mode",
  );
  assert.equal(
    d.getElementById("account-mode-context").classList.contains("hidden"),
    true,
  );
  assert.equal(
    d.getElementById("paper-position-panel").classList.contains("hidden"),
    true,
  );
});

test("a failed positions refresh never claims that an empty cached snapshot is the current account", async (t) => {
  const stale = structuredClone(ready);
  stale.status = "partial";
  stale.sections.positions = {
    updated_at: 1700000000,
    rows: [],
    error: "Demo API unavailable after three read attempts",
  };
  const { document: d } = await dashboard(t, stale);
  assert.match(
    d.getElementById("account-positions").textContent,
    /Current data unavailable/,
  );
  assert.doesNotMatch(
    d.getElementById("account-positions").textContent,
    /No open positions/,
  );
  assert.equal(d.getElementById("account-unrealized").textContent, "—");
});

test("a year preset submits isolated backtest settings and never starts trading", async (t) => {
  const { document: d, calls, state } = await dashboard(t);
  d.getElementById("backtest-tab").click();
  d.querySelector('[data-days="365"]').click();
  d.getElementById("backtest-setting-symbol").value = "ETHUSD";
  d.getElementById("backtest-form").dispatchEvent(
    new d.defaultView.Event("submit", { cancelable: true, bubbles: true }),
  );
  await settle();
  const request = calls.find((c) => c.url === "/api/backtests" && c.body)?.body;
  assert.equal(request.settings.symbol, "ETHUSD");
  assert.equal(request.source, "india_public");
  assert.ok(
    request.end - request.start >= 365 * 86400 &&
      request.end - request.start <= 366 * 86400,
  );
  assert.equal(state.settings.symbol, "BTCUSD");
  assert.ok(
    !calls.some((c) => ["/api/start", "/api/settings"].includes(c.url)),
  );
  assert.equal(d.getElementById("backtest-run").disabled, true);
});

test("results render a large equity series without argument limits and paginate trades", async (t) => {
  const { w, document: d } = await dashboard(t);
  const result = {
    source: "Delta India public market history",
    quote: "USD",
    settings,
    candles: 105120,
    warmup_candles: 600,
    ambiguous_candles: 1,
    actual_start: 1700000000,
    actual_end: 1731536000,
    summary: {
      net_pnl: 0,
      return_percent: 0,
      trades: 0,
      win_rate: null,
      max_drawdown_percent: 0,
      fees: 0,
      profit_factor: null,
      gross_profit: 0,
      ending_equity: 10000,
    },
    trades: [],
    equity_curve: Array.from({ length: 530000 }, (_, i) => ({
      time: 1700000000 + i * 60,
      equity: 10000 + i * 0.001,
    })),
    assumptions: ["Stops take priority"],
    rejected_entries: {},
    reference_checks: [
      {
        name: "PyBacktestPro",
        url: "https://github.com/raviwijerathna1/PyBacktestPro",
        status: "passed",
        checks: { trades: { passed: true } },
      },
      {
        name: "Backtrader",
        url: "https://github.com/mementum/backtrader",
        kind: "execution_scenarios",
        status: "passed",
        message: "20/20 controlled broker scenarios agree.",
        scope:
          "Controlled bracket execution; not a replay of this strategy or period.",
        limitations: ["Entry-candle activation timing is not compared."],
      },
    ],
  };
  w.setBacktestJob({ status: "completed", message: "Complete", result });
  assert.equal(
    d.getElementById("backtest-results").classList.contains("hidden"),
    false,
  );
  assert.match(d.getElementById("bt-trade-rows").textContent, /No signals/);
  assert.match(
    d.getElementById("bt-reference-checks").textContent,
    /Metrics agree/,
  );
  const execution = [...d.querySelectorAll(".reference-check")].find(
    (row) => row.querySelector("a").textContent === "Backtrader",
  );
  assert.match(execution.textContent, /Bracket checks passed/);
  assert.doesNotMatch(execution.textContent, /Metrics agree/);
  assert.match(execution.querySelector("details").textContent, /not a replay/);
  assert.match(
    execution.querySelector("details li").textContent,
    /activation timing/,
  );
  assert.ok(
    d.querySelector("#equity-chart polyline").getAttribute("points").split(" ")
      .length <= 1503,
  );
});

test("dashboard text has a 12px minimum and readable form controls", async (t) => {
  const { w, document: d } = await dashboard(t);
  const ids = [...d.querySelectorAll("[id]")].map((e) => e.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const el of d.querySelectorAll("p,label,small,th,td,button,h2,h1")) {
    const size = parseFloat(w.getComputedStyle(el).fontSize);
    assert.ok(
      size >= 12,
      `${el.tagName} ${el.id || el.className} has ${size}px text`,
    );
  }
  assert.ok(
    parseFloat(w.getComputedStyle(d.getElementById("api-key")).fontSize) >= 16,
  );
});

test("backtest advanced settings stay separate from the essential setup and submit their edits", async (t) => {
  const { document: d, calls } = await dashboard(t);
  const advanced = d.getElementById("backtest-settings-dialog");
  assert.equal(advanced.open, false);
  assert.equal(
    d.getElementById("backtest-market-inputs").querySelectorAll("input,select")
      .length,
    4,
  );
  assert.ok(advanced.contains(d.getElementById("backtest-setting-fast_ema")));
  assert.ok(advanced.contains(d.getElementById("backtest-setting-tp0")));
  d.getElementById("backtest-settings-open").click();
  assert.equal(advanced.open, true);
  d.getElementById("bt-settings-risk").click();
  assert.equal(
    d.getElementById("bt-settings-risk").getAttribute("aria-selected"),
    "true",
  );
  d.getElementById("backtest-setting-sl_atr").value = "2.5";
  d.getElementById("backtest-settings-done").click();
  assert.equal(advanced.open, false);
  assert.equal(
    calls.filter((c) => c.url === "/api/backtests" && c.body).length,
    0,
  );
  d.getElementById("backtest-form").dispatchEvent(
    new d.defaultView.Event("submit", { cancelable: true, bubbles: true }),
  );
  await settle();
  assert.equal(
    calls.find((c) => c.url === "/api/backtests" && c.body).body.settings
      .sl_atr,
    2.5,
  );
});

test("invalid hidden strategy controls open the correct settings tab", async (t) => {
  const { document: d } = await dashboard(t);
  const input = d.getElementById("backtest-setting-tp0");
  input.value = "-1";
  input.dispatchEvent(new d.defaultView.Event("invalid", { cancelable: true }));
  assert.equal(d.getElementById("backtest-settings-dialog").open, true);
  assert.equal(
    d.getElementById("bt-settings-risk").getAttribute("aria-selected"),
    "true",
  );
  assert.ok(d.getElementById("backtest-settings-error").textContent.length > 0);
  d.getElementById("backtest-settings-done").click();
  assert.equal(d.getElementById("backtest-settings-dialog").open, true);
  input.value = "1";
  d.getElementById("backtest-settings-done").click();
  assert.equal(d.getElementById("backtest-settings-dialog").open, false);
});

test("result tabs switch with the keyboard and trade details open outside the table", async (t) => {
  const { w, document: d } = await dashboard(t);
  const trade = {
    side: "buy",
    entry_time: 1700000000,
    exit_time: 1700000900,
    entry: 100,
    initial_stop: 80,
    quantity: 4,
    net_pnl: 20,
    fees: 0,
    final_reason: "advanced_stop",
    exits: [
      { time: 1700000900, reason: "tp1", quantity: 2, price: 110, net_pnl: 20 },
      {
        time: 1700000900,
        reason: "advanced_stop",
        quantity: 2,
        price: 100,
        net_pnl: 0,
      },
    ],
    stop_updates: [{ time: 1700000900, after_target: 1, stop: 100 }],
  };
  w.setBacktestJob({
    status: "completed",
    message: "Complete",
    result: {
      source: "Delta demo history",
      quote: "USD",
      settings,
      candles: 3,
      warmup_candles: 600,
      ambiguous_candles: 1,
      actual_start: 1700000000,
      actual_end: 1700000900,
      summary: {
        net_pnl: 20,
        return_percent: 0.2,
        trades: 1,
        win_rate: 100,
        max_drawdown_percent: 0,
        fees: 0,
        profit_factor: null,
        gross_profit: 20,
        ending_equity: 10020,
      },
      trades: [trade],
      equity_curve: [
        { time: 1700000000, equity: 10000 },
        { time: 1700000900, equity: 10020 },
      ],
      assumptions: ["Conservative stops"],
      rejected_entries: {},
      reference_checks: [],
    },
  });
  assert.equal(
    d.getElementById("bt-overview-panel").classList.contains("hidden"),
    false,
  );
  assert.equal(
    d.getElementById("bt-trade-panel").classList.contains("hidden"),
    true,
  );
  assert.equal(
    d.getElementById("bt-methodology-panel").classList.contains("hidden"),
    true,
  );
  d.getElementById("bt-tab-overview").dispatchEvent(
    new w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
  );
  assert.equal(
    d.getElementById("bt-tab-trades").getAttribute("aria-selected"),
    "true",
  );
  assert.equal(
    d.getElementById("bt-overview-panel").classList.contains("hidden"),
    true,
  );
  d.querySelector("#bt-trade-rows .bt-trade-link").click();
  assert.equal(d.getElementById("bt-trade-dialog").open, true);
  assert.equal(d.querySelectorAll("#bt-trade-timeline li").length, 3);
  assert.match(
    d.querySelector("#bt-trade-timeline li:nth-child(2)").textContent,
    /Stop updated after TP1/,
  );
  assert.equal(d.querySelector("#bt-trade-rows details"), null);
  d.getElementById("bt-trade-close").click();
  d.getElementById("bt-tab-methodology").click();
  assert.equal(
    d.getElementById("bt-methodology-panel").classList.contains("hidden"),
    false,
  );
  assert.equal(
    d.getElementById("bt-trade-panel").classList.contains("hidden"),
    true,
  );
});
