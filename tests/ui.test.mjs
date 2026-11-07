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
async function dashboard(t, account = ready, status = initial) {
  const css = readFileSync("bot/static/style.css", "utf8");
  const html = readFileSync("bot/static/index.html", "utf8").replace(
    "</head>",
    `<style>${css}</style></head>`,
  );
  const dom = new JSDOM(html, {
    url: "http://127.0.0.1:8001",
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

test("a paused paper position remains visible in Account without inventing exchange holdings", async (t) => {
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
  assert.match(
    d.getElementById("account-notice").textContent,
    /paper simulation/,
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
      ["/api/start", "/api/settings", "/api/reconcile"].includes(c.url),
    ),
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
