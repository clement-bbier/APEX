"""Enhanced APEX Command Center Dashboard.

Real-time web interface for monitoring and controlling the APEX trading system.
Built with FastAPI + WebSocket + Chart.js + plain HTML/CSS.

Features:
  - System health grid (10 services, color-coded)
  - Live equity curve (Chart.js, updates every 2s)
  - Open positions table with unrealized PnL
  - Recent signals feed
  - Circuit breaker panel with manual reset
  - Regime dashboard with macros
  - Upcoming CB events countdown
  - Performance stats (Sharpe, DD, win rate)
  - Alert log

Architecture: read-only dashboard. No order placement from UI.
Orders only via ZMQ pipeline (per CLAUDE.md security rules).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("s10_monitor.dashboard")

# ── HTML Template ──────────────────────────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX Command Center</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --green: #39d353; --red: #f85149; --yellow: #e3b341;
    --blue: #58a6ff; --purple: #bc8cff; --orange: #ff7b72;
    --text: #c9d1d9; --text2: #8b949e; --border: #30363d;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'SF Mono',monospace; font-size:13px; }
  header { background:var(--bg2); border-bottom:1px solid var(--border); padding:12px 20px;
           display:flex; align-items:center; justify-content:space-between; }
  header h1 { color:var(--blue); font-size:18px; letter-spacing:2px; }
  header .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; }
  .dot-green { background:var(--green); animation:pulse 2s infinite; }
  .dot-red { background:var(--red); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .grid { display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; padding:12px; }
  .grid-wide { grid-column: span 2; }
  .grid-full { grid-column: span 3; }
  .card { background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:14px; }
  .card h2 { color:var(--text2); font-size:11px; text-transform:uppercase; letter-spacing:1px;
             margin-bottom:10px; border-bottom:1px solid var(--border); padding-bottom:6px; }
  .metric { display:flex; justify-content:space-between; align-items:center; margin:4px 0; }
  .metric-val { font-size:20px; font-weight:bold; }
  .green { color:var(--green); }
  .red { color:var(--red); }
  .yellow { color:var(--yellow); }
  .blue { color:var(--blue); }
  .purple { color:var(--purple); }
  .services-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; }
  .svc { padding:6px 8px; border-radius:6px; text-align:center; font-size:11px; }
  .svc.ok { background:#1c3a1c; border:1px solid var(--green); color:var(--green); }
  .svc.warn { background:#3a2a0a; border:1px solid var(--yellow); color:var(--yellow); }
  .svc.dead { background:#3a0a0a; border:1px solid var(--red); color:var(--red); }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th { color:var(--text2); text-align:left; padding:4px 8px; border-bottom:1px solid var(--border); }
  td { padding:5px 8px; border-bottom:1px solid var(--border); }
  .cb-panel { padding:10px; border-radius:6px; text-align:center; }
  .cb-closed { background:#0d2b0d; border:2px solid var(--green); }
  .cb-open { background:#2b0d0d; border:2px solid var(--red); }
  .cb-half { background:#2b1f0d; border:2px solid var(--yellow); }
  .cb-state { font-size:22px; font-weight:bold; margin:6px 0; }
  button { background:var(--bg3); border:1px solid var(--border); color:var(--text);
           padding:6px 14px; border-radius:6px; cursor:pointer; font-size:12px; margin-top:8px; }
  button:hover { background:var(--red); border-color:var(--red); }
  .regime-pill { display:inline-block; padding:2px 10px; border-radius:12px; font-size:11px; margin:2px; }
  .signal-row { display:flex; justify-content:space-between; padding:4px 0;
                border-bottom:1px solid var(--border); }
  .signal-dir-long { color:var(--green); }
  .signal-dir-short { color:var(--red); }
  .bar-fill { height:8px; border-radius:4px; background:var(--green); transition:width .5s; }
  .bar-track { background:var(--bg3); border-radius:4px; overflow:hidden; margin:4px 0; }
  .alert-item { padding:4px 8px; margin:3px 0; border-radius:4px; font-size:11px; }
  .alert-WARNING { background:#2b1f0d; border-left:3px solid var(--yellow); }
  .alert-CRITICAL { background:#2b0d0d; border-left:3px solid var(--red); }
  .alert-INFO { background:#0d1f2b; border-left:3px solid var(--blue); }
  #connection-status { font-size:11px; color:var(--text2); }
  .event-row { display:flex; justify-content:space-between; padding:4px 0;
               border-bottom:1px solid var(--border); }
  .event-soon { color:var(--red); }
  .event-soon2 { color:var(--yellow); }
  canvas { max-height: 200px; }
</style>
</head>
<body>
<header>
  <div>
    <span class="status-dot dot-green" id="conn-dot"></span>
    <h1 style="display:inline">APEX Command Center</h1>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <span id="connection-status">Connecting...</span>
    <span id="trading-mode" class="regime-pill" style="background:#1c2d1c;border:1px solid var(--green)">PAPER</span>
    <span id="clock" class="blue"></span>
  </div>
</header>

<div class="grid">

  <!-- PnL Summary -->
  <div class="card">
    <h2>P&amp;L Today</h2>
    <div class="metric"><span>Realized</span><span id="pnl-realized" class="metric-val green">$0.00</span></div>
    <div class="metric"><span>Unrealized</span><span id="pnl-unrealized" class="metric-val">$0.00</span></div>
    <div class="metric"><span>Daily %</span><span id="pnl-pct" class="metric-val">0.00%</span></div>
    <div class="metric"><span>Max DD</span><span id="max-dd" class="metric-val red">0.00%</span></div>
    <div class="metric"><span>Trades today</span><span id="trade-count" class="blue">0</span></div>
    <div class="metric"><span>Win rate (50)</span><span id="win-rate" class="green">0.0%</span></div>
  </div>

  <!-- Equity Curve -->
  <div class="card grid-wide">
    <h2>Equity Curve</h2>
    <canvas id="equityChart"></canvas>
  </div>

  <!-- Risk Manager -->
  <div class="card grid-wide">
    <h2>Risk Manager</h2>
    <div style="display:flex; gap:20px; align-items: flex-start;">
      <!-- CB Panel -->
      <div style="flex:1">
        <div id="cb-panel" class="cb-panel cb-closed">
          <div style="font-size:11px;color:var(--text2)">C.B. STATUS</div>
          <div id="cb-state" class="cb-state green">CLOSED</div>
          <div id="cb-allows" style="font-size:11px" class="green">Orders allowed</div>
        </div>
        <button onclick="resetCB()" id="cb-reset-btn" style="display:none;background:var(--red);margin-top:8px">
          Reset Circuit Breaker
        </button>
        <div id="cb-daily-pnl" style="margin-top:8px;font-size:11px;color:var(--text2)"></div>
      </div>
      <!-- Exposure -->
      <div style="flex: 1;">
        <div style="font-size:11px;color:var(--text2);margin-bottom:4px">Total Exposure (<span id="exp-text">0.0%</span>/20%)</div>
        <div class="bar-track"><div id="exp-bar" class="bar-fill" style="width:0%"></div></div>

        <div style="font-size:11px;color:var(--text2);margin-bottom:4px;margin-top:10px">Approval Rate (Last 100) <span id="ar-text">0.0%</span></div>
        <div class="bar-track"><div id="ar-bar" class="bar-fill" style="width:0%; background:var(--blue)"></div></div>
      </div>
      <!-- Blocks & Kelly -->
      <div style="flex: 1.5;font-size:11px;">
        <div style="color:var(--text2);margin-bottom:4px">Kelly Fractions (recent)</div>
        <div style="display:flex; gap:2px; height:30px; align-items:flex-end; border-bottom:1px solid var(--border)" id="kelly-spark"></div>
        <div style="color:var(--text2);margin-top:10px;margin-bottom:4px">Block Reasons (Last 100)</div>
        <div id="block-reasons-list"></div>
      </div>
    </div>
  </div>

  <!-- Regime Dashboard -->
  <div class="card">
    <h2>Market Regime</h2>
    <div class="metric"><span>Vol Regime</span><span id="vol-regime" class="yellow">-</span></div>
    <div class="metric"><span>Trend</span><span id="trend-regime" class="blue">-</span></div>
    <div class="metric"><span>Risk Mode</span><span id="risk-mode" class="green">-</span></div>
    <div class="metric"><span>Macro Mult</span><span id="macro-mult" class="purple">-</span></div>
    <div class="metric"><span>Session</span><span id="session" class="blue">-</span></div>
    <div class="metric"><span>Session Mult</span><span id="session-mult" class="green">-</span></div>
    <div id="event-active" style="margin-top:8px;font-size:11px;display:none"
         class="red">CB EVENT ACTIVE - TRADING BLOCKED</div>
  </div>

  <!-- Performance Stats -->
  <div class="card">
    <h2>Performance Metrics</h2>
    <div class="metric"><span>Sharpe (rolling)</span><span id="sharpe" class="green">-</span></div>
    <div class="metric"><span>Sortino</span><span id="sortino" class="green">-</span></div>
    <div class="metric"><span>Profit Factor</span><span id="profit-factor" class="blue">-</span></div>
    <div class="metric"><span>Best Session</span><span id="best-session" class="purple">-</span></div>
    <div class="metric"><span>Best Signal</span><span id="best-signal" class="purple">-</span></div>
    <div style="margin-top:10px">
      <div style="font-size:11px;color:var(--text2);margin-bottom:4px">Win Rate</div>
      <div class="bar-track"><div id="wr-bar" class="bar-fill" style="width:0%"></div></div>
    </div>
  </div>

  <!-- Services Health -->
  <div class="card grid-full">
    <h2>Services Health</h2>
    <div class="services-grid" id="services-grid">
      <div class="svc warn">Loading...</div>
    </div>
  </div>

  <!-- Open Positions -->
  <div class="card grid-wide">
    <h2>Open Positions</h2>
    <table>
      <thead><tr><th>Symbol</th><th>Direction</th><th>Entry</th><th>Size</th><th>Unreal. PnL</th><th>Session</th></tr></thead>
      <tbody id="positions-tbody"><tr><td colspan="6" style="color:var(--text2);text-align:center">No open positions</td></tr></tbody>
    </table>
  </div>

  <!-- CB Events -->
  <div class="card">
    <h2>CB Events Calendar</h2>
    <div id="cb-events-list"><div style="color:var(--text2)">Loading...</div></div>
  </div>

  <!-- Recent Signals -->
  <div class="card grid-wide">
    <h2>Signal Feed</h2>
    <div id="signals-feed"></div>
  </div>

  <!-- Alert Log -->
  <div class="card">
    <h2>Recent Alerts</h2>
    <div id="alerts-log" style="max-height:200px;overflow-y:auto"></div>
  </div>

</div>

<script>
function updateClock() {
  document.getElementById('clock').textContent = new Date().toUTCString().slice(17, 25) + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

const ctx = document.getElementById('equityChart').getContext('2d');
const equityChart = new Chart(ctx, {
  type: 'line',
  data: { labels: [], datasets: [{
    label: 'Equity', data: [], borderColor: '#39d353', backgroundColor: 'rgba(57,211,83,0.1)',
    fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
  }]},
  options: {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y: { grid: { color: '#21262d' }, ticks: { color: '#8b949e', font: { size: 10 } } }
    }
  }
});

let ws;
function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => {
    document.getElementById('connection-status').textContent = 'Connected';
    document.getElementById('conn-dot').className = 'status-dot dot-green';
  };
  ws.onclose = () => {
    document.getElementById('connection-status').textContent = 'Reconnecting...';
    document.getElementById('conn-dot').className = 'status-dot dot-red';
    setTimeout(connect, 3000);
  };
  ws.onmessage = (e) => {
    try { render(JSON.parse(e.data)); } catch(err) { console.error(err); }
  };
}

function render(d) {
  if (d.pnl) {
    const p = d.pnl;
    setText('pnl-realized', p.realized_today || '$0.00');
    setText('pnl-pct', (p.daily_pnl_pct > 0 ? '+' : '') + (p.daily_pnl_pct || 0).toFixed(3) + '%');
    colorize('pnl-pct', p.daily_pnl_pct);
    setText('max-dd', (p.max_drawdown_pct || 0).toFixed(3) + '%');
    setText('trade-count', p.trade_count_today || 0);
    setText('win-rate', ((p.win_rate_rolling || 0) * 100).toFixed(1) + '%');
    colorize('win-rate', (p.win_rate_rolling || 0) - 0.5);
  }
  if (d.equity && d.equity.length) {
    const vals = d.equity.map(e => typeof e === 'object' ? parseFloat(e.equity || 0) : parseFloat(e || 0));
    equityChart.data.labels = vals.map((_, i) => i);
    equityChart.data.datasets[0].data = vals;
    equityChart.update('none');
  }
  if (d.circuit_breaker) {
    const cb = d.circuit_breaker;
    const state = (cb.state || 'CLOSED').toUpperCase();
    const panel = document.getElementById('cb-panel');
    const stateEl = document.getElementById('cb-state');
    const allowsEl = document.getElementById('cb-allows');
    if (stateEl && allowsEl && panel) {
      stateEl.textContent = state;
      panel.className = 'cb-panel ' + (state === 'CLOSED' ? 'cb-closed' : state === 'OPEN' ? 'cb-open' : 'cb-half');
      stateEl.className = 'cb-state ' + (state === 'CLOSED' ? 'green' : state === 'OPEN' ? 'red' : 'yellow');
      allowsEl.textContent = cb.allows_new_orders ? 'Orders allowed' : 'Orders BLOCKED';
      allowsEl.className = cb.allows_new_orders ? 'green' : 'red';
      document.getElementById('cb-reset-btn').style.display = state !== 'CLOSED' ? 'block' : 'none';
      document.getElementById('cb-daily-pnl').textContent = 'Daily PnL: ' + (cb.daily_pnl_pct || 0).toFixed(3) + '% (limit: -3%)';
    }
  }
  if (d.risk) {
    const r = d.risk;
    const d100 = r.decisions_last_100 || {};
    const kelly = r.kelly_stats || {};
    const expPct = (r.portfolio.total_exposure_pct || 0) * 100;

    if (document.getElementById('exp-text')) {
      document.getElementById('exp-text').textContent = expPct.toFixed(1) + '%';
      const expBar = document.getElementById('exp-bar');
      expBar.style.width = Math.min(expPct / 20 * 100, 100) + '%';
      expBar.style.background = expPct > 15 ? 'var(--red)' : '';

      document.getElementById('ar-text').textContent = (d100.approval_rate_pct || 0).toFixed(1) + '%';
      document.getElementById('ar-bar').style.width = (d100.approval_rate_pct || 0) + '%';

      const spark = document.getElementById('kelly-spark');
      if (kelly.sparkline && kelly.sparkline.length) {
        spark.innerHTML = kelly.sparkline.map(v =>
          '<div style="flex:1;background:var(--purple);height:'+ (v*100) +'%">%</div>'
        ).join('');
      }

      const br = r.block_reasons || {};
      const brList = Object.entries(br).sort((a,b)=>b[1]-a[1]).map(x => '<div style="margin-bottom:2px">'+x[0]+': '+x[1]+'</div>').join('');
      document.getElementById('block-reasons-list').innerHTML = brList || 'none';
    }
  }
  if (d.regime) {
    const r = d.regime;
    setText('vol-regime', r.vol_regime || '-');
    setText('trend-regime', r.trend_regime || '-');
    setText('risk-mode', r.risk_mode || '-');
    setText('macro-mult', 'x' + (r.macro_mult || 1.0).toFixed(2));
    setText('session', r.session || '-');
    setText('session-mult', 'x' + (r.session_mult || 1.0).toFixed(2));
    document.getElementById('event-active').style.display = r.event_active ? 'block' : 'none';
  }
  if (d.services && d.services.length) {
    const grid = document.getElementById('services-grid');
    grid.innerHTML = d.services.map(s => {
      const cls = s.is_alive ? 'ok' : (s.last_seen_seconds < 30 ? 'warn' : 'dead');
      const label = s.service_id.replace('_', ' ').replace('s0', 'S').replace('s1', 'S1');
      return '<div class="svc ' + cls + '" title="' + s.last_seen_seconds.toFixed(0) + 's ago">' + label + '</div>';
    }).join('');
  }
  if (d.positions !== undefined) {
    const tbody = document.getElementById('positions-tbody');
    if (!d.positions.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text2);text-align:center;padding:12px">No open positions</td></tr>';
    } else {
      tbody.innerHTML = d.positions.map(p => {
        const cls = p.unrealized_pnl_pct >= 0 ? 'green' : 'red';
        const dir = p.direction === 'long' ? '<span class="green">LONG</span>' : '<span class="red">SHORT</span>';
        return '<tr><td class="blue">' + p.symbol + '</td><td>' + dir + '</td><td>' + p.entry_price + '</td>' +
               '<td>' + p.size + '</td><td class="' + cls + '">' + (p.unrealized_pnl_pct > 0 ? '+' : '') + p.unrealized_pnl_pct.toFixed(3) + '%</td>' +
               '<td class="purple">' + p.session + '</td></tr>';
      }).join('');
    }
  }
  if (d.signals && d.signals.length) {
    const feed = document.getElementById('signals-feed');
    feed.innerHTML = d.signals.slice(0, 10).map(s => {
      const dirCls = s.direction === 'long' ? 'signal-dir-long' : 'signal-dir-short';
      const strength = Math.abs(s.strength || 0);
      return '<div class="signal-row">' +
        '<span class="blue">' + s.symbol + '</span>' +
        '<span class="' + dirCls + '">' + s.direction.toUpperCase() + '</span>' +
        '<span>str: <span class="green">' + strength.toFixed(2) + '</span></span>' +
        '<span style="color:var(--text2)">[' + (s.triggers||[]).join(', ') + ']</span>' +
        '<span style="color:var(--text2)">' + s.age_seconds.toFixed(0) + 's ago</span>' +
        '</div>';
    }).join('');
  }
  if (d.performance) {
    const p = d.performance;
    setText('sharpe', (p.sharpe_daily || 0).toFixed(3));
    colorize('sharpe', p.sharpe_daily || 0);
    setText('sortino', (p.sortino_daily || 0).toFixed(3));
    colorize('sortino', p.sortino_daily || 0);
    setText('profit-factor', (p.profit_factor || 0).toFixed(2));
    setText('best-session', p.best_session || '-');
    setText('best-signal', p.best_signal_type || '-');
    const wr = (p.win_rate || 0) * 100;
    document.getElementById('wr-bar').style.width = wr.toFixed(1) + '%';
    document.getElementById('wr-bar').style.background = wr > 55 ? '#39d353' : wr > 45 ? '#e3b341' : '#f85149';
  }
  if (d.cb_events !== undefined) {
    const list = document.getElementById('cb-events-list');
    if (!d.cb_events.length) {
      list.innerHTML = '<div style="color:var(--text2)">No upcoming events</div>';
    } else {
      list.innerHTML = d.cb_events.map(ev => {
        const mins = ev.minutes_until;
        const cls = mins < 45 ? 'event-soon' : mins < 120 ? 'event-soon2' : '';
        const icon = ev.block_active ? '[BLOCK]' : ev.monitor_active ? '[WATCH]' : '[OK]';
        return '<div class="event-row">' +
          '<span>' + icon + ' <span class="blue">' + ev.institution + '</span> ' + ev.event_type + '</span>' +
          '<span class="' + cls + '">' + (mins > 0 ? '+' : '') + mins.toFixed(0) + 'min</span>' +
          '</div>';
      }).join('');
    }
  }
  if (d.alerts !== undefined) {
    const log = document.getElementById('alerts-log');
    if (!d.alerts.length) {
      log.innerHTML = '<div style="color:var(--text2);font-size:11px">No alerts</div>';
    } else {
      log.innerHTML = d.alerts.slice(0, 20).map(a =>
        '<div class="alert-item alert-' + a.level + '">' +
        '<span style="color:var(--text2)">' + (a.timestamp||'').slice(0,19) + '</span>' +
        '<span class="' + (a.level==='CRITICAL'?'red':a.level==='WARNING'?'yellow':'blue') + '"> ' + a.level + '</span>' +
        '<div>' + a.message + '</div></div>'
      ).join('');
    }
  }
  if (d.system) {
    const mode = d.system.trading_mode || 'PAPER';
    const el = document.getElementById('trading-mode');
    el.textContent = mode;
    el.style.background = mode === 'LIVE' ? '#2b0d0d' : '#0d2b0d';
    el.style.borderColor = mode === 'LIVE' ? '#f85149' : '#39d353';
    el.style.color = mode === 'LIVE' ? '#f85149' : '#39d353';
  }
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
function colorize(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = parseFloat(val) >= 0 ? 'green' : 'red';
}

async function resetCB() {
  if (!confirm('Reset circuit breaker to CLOSED? Only do this at start of trading day after reviewing risk.')) return;
  try {
    const r = await fetch('/api/v1/circuit-breaker/reset', {
      method: 'POST', headers: { 'X-Confirm': 'YES' }
    });
    const data = await r.json();
    alert(data.message);
  } catch (e) { alert('Error: ' + e); }
}

connect();
</script>
</body>
</html>"""


# ── WebSocket Connection Manager ───────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# ── Dashboard Server ───────────────────────────────────────────────────────────

class DashboardServer:
    """APEX Command Center server — FastAPI + WebSocket + REST API."""

    def __init__(
        self, state: StateStore, host: str = "0.0.0.0", port: int = 8080,
    ) -> None:
        self._state = state
        self._host = host
        self._port = port
        self._manager = ConnectionManager()
        self.app = FastAPI(title="APEX Command Center", version="1.0.0")
        self._setup_routes()

    def _setup_routes(self) -> None:
        app = self.app
        state = self._state

        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(_DASHBOARD_HTML)

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {"status": "ok", "timestamp": time.time()}

        @app.get("/api/v1/system/status")
        async def system_status() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_system_status
            r = await get_system_status(state)
            return r.model_dump()

        @app.get("/api/v1/positions")
        async def positions() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_positions
            return [p.model_dump() for p in await get_positions(state)]

        @app.get("/api/v1/pnl")
        async def pnl() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_pnl
            return (await get_pnl(state)).model_dump()

        @app.get("/api/v1/regime")
        async def regime() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_regime
            return (await get_regime(state)).model_dump()

        @app.get("/api/v1/signals/recent")
        async def signals() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_recent_signals
            return [s.model_dump() for s in await get_recent_signals(state)]

        @app.get("/api/v1/circuit-breaker")
        async def cb() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_circuit_breaker
            return await get_circuit_breaker(state)

        @app.get("/api/v1/risk")
        async def risk() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_risk_status
            return await get_risk_status(state)

        @app.post("/api/v1/circuit-breaker/reset")
        async def cb_reset(x_confirm: str | None = None) -> dict[str, Any]:
            from services.s10_monitor.command_api import reset_circuit_breaker
            r = await reset_circuit_breaker(state, x_confirm)
            return r.model_dump()

        @app.get("/api/v1/performance")
        async def perf() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_performance
            return (await get_performance(state)).model_dump()

        @app.get("/api/v1/cb-events")
        async def cb_events() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_cb_events
            return [e.model_dump() for e in await get_cb_events(state)]

        @app.get("/api/v1/config")
        async def config() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_config
            return await get_config()

        @app.get("/api/v1/alerts/recent")
        async def alerts() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_recent_alerts
            return [a.model_dump() for a in await get_recent_alerts(state)]

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket) -> None:
            await self._manager.connect(ws)
            try:
                while True:
                    payload = await self._build_broadcast()
                    await self._manager.broadcast(payload)
                    await asyncio.sleep(2.0)
            except WebSocketDisconnect:
                self._manager.disconnect(ws)
            except Exception as exc:
                logger.error("ws_error", error=str(exc))
                self._manager.disconnect(ws)

    async def _build_broadcast(self) -> dict[str, Any]:
        """Build the complete dashboard payload for WebSocket broadcast."""
        from services.s10_monitor.command_api import (
            get_cb_events,
            get_circuit_breaker,
            get_performance,
            get_pnl,
            get_positions,
            get_recent_alerts,
            get_recent_signals,
            get_regime,
            get_risk_status,
            get_system_status,
        )
        state = self._state
        payload: dict[str, Any] = {}
        try:
            results = await asyncio.gather(
                get_pnl(state),
                get_positions(state),
                get_regime(state),
                get_recent_signals(state),
                get_circuit_breaker(state),
                get_performance(state),
                get_cb_events(state),
                get_recent_alerts(state),
                get_system_status(state),
                get_risk_status(state),
                return_exceptions=True,
            )
            labels = ["pnl", "positions", "regime", "signals", "circuit_breaker",
                      "performance", "cb_events", "alerts", "system", "risk"]
            for label, result in zip(labels, results, strict=True):
                if isinstance(result, Exception):
                    logger.debug("broadcast_partial_fail", label=label, error=str(result))
                    continue
                if hasattr(result, "model_dump"):
                    payload[label] = result.model_dump()
                elif isinstance(result, list):
                    payload[label] = [r.model_dump() if hasattr(r, "model_dump") else r for r in result]
                else:
                    payload[label] = result

            # Equity curve
            curve = await state.lrange("equity_curve", 0, 99)
            payload["equity"] = list(reversed(curve))  # chronological order

        except Exception as exc:
            payload["error"] = str(exc)
        return payload

    async def start(self) -> None:
        config = uvicorn.Config(self.app, host=self._host, port=self._port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()

