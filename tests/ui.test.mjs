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
async function dashboard(t, account = ready) {
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
    state = structuredClone(initial),
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
