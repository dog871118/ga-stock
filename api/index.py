from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

# ────────────────────────────────────────────
#  訊號計算邏輯（不變）
# ────────────────────────────────────────────
def calc_signal(close_series):
    """計算四狀態訊號（回溯20期）"""
    if len(close_series) < 5:
        return '⬜', '空手', 0

    status  = 'watching'
    buy_day = None

    for i in range(2, len(close_series)):
        price      = float(close_series.iloc[i])
        prev2_high = float(close_series.iloc[i-2:i].max())
        prev2_low  = float(close_series.iloc[i-2:i].min())

        if status == 'watching':
            if price > prev2_high:
                status  = 'holding'
                buy_day = i
        else:
            if price < prev2_low:
                status  = 'watching'
                buy_day = None

    price      = float(close_series.iloc[-1])
    prev2_high = float(close_series.iloc[-3:-1].max())
    prev2_low  = float(close_series.iloc[-3:-1].min())

    if status == 'holding':
        if price < prev2_low:
            signal, action = '🔴', '賣出'
        elif buy_day == len(close_series) - 1:
            signal, action = '🟢', '買進'
        else:
            signal, action = '🟡', '持有'
        hold_days = (len(close_series) - 1) - buy_day if buy_day is not None else 0
    else:
        if price > prev2_high:
            signal, action = '🟢', '買進'
        else:
            signal, action = '⬜', '空手'
        hold_days = 0

    return signal, action, hold_days


def resolve_ticker(stock_id):
    """自動判斷上市(.TW)或上櫃(.TWO)，回傳正確 ticker"""
    if stock_id.endswith(".TW") or stock_id.endswith(".TWO"):
        return stock_id
    # 先試上市
    t = stock_id + ".TW"
    try:
        df = yf.download(t, period="5d", auto_adjust=True, progress=False)
        if not df.empty and len(df) >= 1:
            return t
    except:
        pass
    # 再試上櫃
    return stock_id + ".TWO"


def get_signals(stock_id):
    try:
        ticker = resolve_ticker(stock_id)

        # 日線
        df_d = yf.download(ticker, period="40d", auto_adjust=True, progress=False)
        if df_d.empty or len(df_d) < 5:
            return None

        if isinstance(df_d.columns, pd.MultiIndex):
            close_d = df_d['Close'].iloc[:, 0].dropna()
        else:
            close_d = df_d['Close'].dropna()

        close_d = close_d.iloc[-20:]
        price   = round(float(close_d.iloc[-1]), 2)
        d_signal, d_action, d_days = calc_signal(close_d)

        # 週線
        df_w = yf.download(ticker, period="60wk", interval="1wk",
                           auto_adjust=True, progress=False)
        if df_w.empty or len(df_w) < 5:
            w_signal, w_action, w_days = '⬜', '空手', 0
        else:
            if isinstance(df_w.columns, pd.MultiIndex):
                close_w = df_w['Close'].iloc[:, 0].dropna()
            else:
                close_w = df_w['Close'].dropna()
            close_w = close_w.iloc[-20:]
            w_signal, w_action, w_days = calc_signal(close_w)

        return {
            'price':   price,
            'daily':   {'signal': d_signal, 'action': d_action, 'days': d_days},
            'weekly':  {'signal': w_signal, 'action': w_action, 'days': w_days},
        }
    except:
        return None


# ────────────────────────────────────────────
#  API 路由
# ────────────────────────────────────────────
@app.route('/api/check', methods=['GET'])
def check_stock():
    stock_id = request.args.get('id', '').strip().upper()
    if not stock_id:
        return jsonify({'error': '請輸入股票代號'}), 400
    result = get_signals(stock_id)
    if result is None:
        return jsonify({'error': '查無資料，請確認代號'}), 404
    return jsonify(result)


@app.route('/api/batch', methods=['GET'])
def batch_check():
    ids_raw = request.args.get('ids', '').strip().upper()
    if not ids_raw:
        return jsonify({'error': '請輸入股票代號'}), 400
    ids = [x.strip() for x in ids_raw.split(',') if x.strip()]
    result = {}
    for sid in ids:
        data = get_signals(sid)
        if data:
            result[sid] = data
    return jsonify(result)


import requests as http_requests
import json as _json

GAS_ENDPOINT = "https://script.google.com/macros/s/AKfycbyD6DnxV3p7j7M2PZzGarqSOBobpADkAsbVV497-YXD-FkWiyfRr55kFie2yw0B4_U8Ow/exec"

@app.route('/api/sync-load', methods=['GET'])
def sync_load():
    try:
        r = http_requests.get(GAS_ENDPOINT, params={'action': 'load'}, timeout=15)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync-save', methods=['POST'])
def sync_save():
    try:
        payload = request.json.get('payload', [])
        r = http_requests.get(GAS_ENDPOINT, params={
            'action': 'save',
            'payload': _json.dumps(payload)
        }, timeout=15)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ────────────────────────────────────────────
#  前端 HTML
# ────────────────────────────────────────────
GAS_URL = "https://script.google.com/macros/s/AKfycbyD6DnxV3p7j7M2PZzGarqSOBobpADkAsbVV497-YXD-FkWiyfRr55kFie2yw0B4_U8Ow/exec"

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>GA 股票訊號</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg:        #0d0f14;
  --surface:   #161a23;
  --border:    #252a38;
  --text:      #e2e8f0;
  --muted:     #64748b;
  --accent:    #38bdf8;
  --accent2:   #818cf8;
  --green:     #4ade80;
  --yellow:    #fbbf24;
  --red:       #f87171;
  --gray:      #475569;
  --radius:    12px;
  --mono:      'DM Mono', monospace;
  --sans:      'Noto Sans TC', sans-serif;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: var(--bg); color: var(--text); font-family: var(--sans); min-height: 100vh; }

/* ── 頂部標題列 ── */
.header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(13,15,20,0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 14px 16px 10px;
}
.header-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.logo { font-family: var(--mono); font-size: 15px; color: var(--accent); letter-spacing: 2px; }
.logo span { color: var(--muted); }
.hist-btn {
  font-size: 12px; padding: 5px 12px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 20px; color: var(--muted); cursor: pointer;
  transition: all .2s;
}
.hist-btn:hover, .hist-btn.active { border-color: var(--accent2); color: var(--accent2); }

/* ── 群組頁籤 ── */
.tabs-wrap { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.tabs-wrap::-webkit-scrollbar { display: none; }
.tab {
  flex-shrink: 0; padding: 5px 14px; border-radius: 20px; font-size: 12px;
  border: 1px solid var(--border); background: transparent;
  color: var(--muted); cursor: pointer; transition: all .2s;
  white-space: nowrap;
}
.tab.active { background: var(--accent); border-color: var(--accent); color: #000; font-weight: 700; }

/* ── 主內容 ── */
.main { padding: 14px 12px 80px; max-width: 480px; margin: 0 auto; }

/* ── 群組標頭 ── */
.group-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
}
.group-name-input {
  flex: 1; background: transparent; border: none; border-bottom: 1px dashed var(--border);
  color: var(--text); font-size: 15px; font-weight: 700; padding: 2px 0;
  font-family: var(--sans);
}
.group-name-input:focus { outline: none; border-bottom-color: var(--accent); }
.scan-btn {
  padding: 6px 16px; background: var(--accent); color: #000;
  border: none; border-radius: 20px; font-size: 12px; font-weight: 700;
  cursor: pointer; transition: all .2s; white-space: nowrap;
}
.scan-btn:hover { background: #7dd3fc; }
.scan-btn:disabled { background: var(--border); color: var(--muted); cursor: default; }
.update-time { font-size: 11px; color: var(--muted); margin-bottom: 8px; font-family: var(--mono); }

/* ── 新增股票列 ── */
.add-row { display: flex; gap: 8px; margin-bottom: 12px; }
.add-input {
  flex: 1; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 9px 12px;
  color: var(--text); font-size: 14px; font-family: var(--mono);
}
.add-input::placeholder { color: var(--muted); }
.add-input:focus { outline: none; border-color: var(--accent); }
.add-input-btn {
  padding: 9px 16px; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); color: var(--accent); font-size: 18px;
  cursor: pointer; transition: all .2s;
}
.add-input-btn:hover { background: var(--accent); color: #000; }

/* ── 股票卡片 ── */
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); margin-bottom: 8px;
  transition: border-color .2s;
  overflow: hidden;
}
.card:hover { border-color: var(--muted); }
.card-main {
  display: flex; align-items: center; padding: 10px 12px; gap: 10px;
}
.stock-id {
  font-family: var(--mono); font-size: 15px; font-weight: 500;
  color: var(--accent); min-width: 58px;
}
.stock-name { font-size: 12px; color: var(--muted); min-width: 40px; }
.signals { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.sig-row { display: flex; align-items: center; gap: 6px; }
.sig-label { font-size: 10px; color: var(--muted); width: 20px; font-family: var(--mono); }
.sig-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  font-weight: 700; letter-spacing: .5px;
}
.sig-green  { background: rgba(74,222,128,.15); color: var(--green); }
.sig-yellow { background: rgba(251,191,36,.15);  color: var(--yellow); }
.sig-red    { background: rgba(248,113,113,.15); color: var(--red); }
.sig-gray   { background: rgba(71,85,105,.2);    color: var(--muted); }
.sig-days { font-size: 11px; color: var(--muted); font-family: var(--mono); }
.price-col { text-align: right; }
.price-val { font-family: var(--mono); font-size: 15px; font-weight: 500; }
.del-btn {
  background: none; border: none; color: var(--muted); cursor: pointer;
  font-size: 16px; padding: 4px; transition: color .2s; line-height: 1;
}
.del-btn:hover { color: var(--red); }
.loading-row { padding: 16px; text-align: center; color: var(--muted); font-size: 13px; }

/* ── 歷史面板 ── */
.hist-panel {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,.7); backdrop-filter: blur(4px);
  display: none; align-items: flex-end;
}
.hist-panel.open { display: flex; }
.hist-inner {
  width: 100%; max-width: 480px; margin: 0 auto;
  background: var(--surface); border-radius: 20px 20px 0 0;
  border: 1px solid var(--border); max-height: 75vh;
  display: flex; flex-direction: column;
}
.hist-header {
  padding: 16px 16px 10px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.hist-title { font-size: 15px; font-weight: 700; }
.hist-close {
  background: none; border: none; color: var(--muted);
  font-size: 22px; cursor: pointer; line-height: 1;
}
.hist-body { overflow-y: auto; padding: 8px 0; }
.hist-day { padding: 4px 16px; }
.hist-date {
  font-size: 11px; font-family: var(--mono); color: var(--accent2);
  padding: 8px 0 4px; border-bottom: 1px solid var(--border); margin-bottom: 4px;
}
.hist-row {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 0; border-bottom: 1px solid rgba(37,42,56,.5);
  font-size: 13px;
}
.hist-sid { font-family: var(--mono); color: var(--accent); min-width: 52px; }
.hist-price { font-family: var(--mono); color: var(--text); min-width: 50px; }
.hist-empty { padding: 24px; text-align: center; color: var(--muted); font-size: 13px; }
.hist-clear-btn {
  margin: 8px 16px; padding: 8px; background: none;
  border: 1px solid var(--border); border-radius: var(--radius);
  color: var(--muted); cursor: pointer; font-size: 12px; width: calc(100% - 32px);
  transition: all .2s;
}
.hist-clear-btn:hover { border-color: var(--red); color: var(--red); }

/* ── 空群組提示 ── */
.empty-hint {
  text-align: center; padding: 32px 0; color: var(--muted); font-size: 13px; line-height: 2;
}

@media (max-width: 360px) {
  .stock-name { display: none; }
}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div class="logo">GA<span>.</span>STOCK</div>
    <div style="display:flex;gap:6px">
      <button class="hist-btn" id="cloudLoadBtn" onclick="loadCloud()">⬇️ 載雲端</button>
      <button class="hist-btn" id="cloudSaveBtn" onclick="saveCloud()">☁️ 存雲端</button>
      <button class="hist-btn" id="histToggle" onclick="toggleHist()">📋 歷史</button>
    </div>
  </div>
  <div class="tabs-wrap" id="tabsWrap"></div>
</div>

<div class="main" id="mainContent"></div>

<!-- 歷史面板 -->
<div class="hist-panel" id="histPanel" onclick="closeHistIfBg(event)">
  <div class="hist-inner">
    <div class="hist-header">
      <div class="hist-title">掃描歷史紀錄</div>
      <button class="hist-close" onclick="toggleHist()">×</button>
    </div>
    <div class="hist-body" id="histBody"></div>
    <button class="hist-clear-btn" onclick="clearHistory()">🗑 清除所有歷史</button>
  </div>
</div>

<script>
// ── 資料存取 ──────────────────────────────────────────
const GROUPS_KEY  = 'ga_groups_v3';
const HISTORY_KEY = 'ga_history_v3';
const DEFAULT_GROUPS = ['短線強勢股','波段持股','觀察名單','自選群組4','自選群組5'];

function loadGroups() {
  try {
    const d = JSON.parse(localStorage.getItem(GROUPS_KEY));
    if (d && d.length === 5) return d;
  } catch(e){}
  return DEFAULT_GROUPS.map(n => ({ name: n, stocks: [] }));
}
function saveGroups() { localStorage.setItem(GROUPS_KEY, JSON.stringify(groups)); }
function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch(e){ return []; }
}
function saveHistory(h) { localStorage.setItem(HISTORY_KEY, JSON.stringify(h)); }

// ── 狀態 ─────────────────────────────────────────────
let groups   = loadGroups();
let curGroup = 0;

// ── 輔助 ─────────────────────────────────────────────
function sigClass(action) {
  return action==='買進'?'sig-green': action==='持有'?'sig-yellow': action==='賣出'?'sig-red':'sig-gray';
}
function nowStr() {
  const d = new Date();
  return d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate()
    +' '+d.getHours()+':'+String(d.getMinutes()).padStart(2,'0');
}
function dateKey() {
  const d = new Date();
  return d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate();
}

// ── 渲染頁籤 ─────────────────────────────────────────
function renderTabs() {
  const w = document.getElementById('tabsWrap');
  w.innerHTML = groups.map((g,i)=>
    `<button class="tab${i===curGroup?' active':''}" onclick="switchTab(${i})">${g.name}</button>`
  ).join('');
}

// ── 渲染主內容 ───────────────────────────────────────
function render() {
  renderTabs();
  const g = groups[curGroup];
  let html = `
    <div class="group-header">
      <input class="group-name-input" value="${g.name}"
        onchange="renameGroup(${curGroup},this.value)"
        onblur="renameGroup(${curGroup},this.value)">
      <button class="scan-btn" id="scanBtn" onclick="scanGroup(${curGroup})">⚡ 掃描</button>
    </div>
    <div class="update-time" id="updateTime${curGroup}">${g.lastUpdate||''}</div>
    <div class="add-row">
      <input class="add-input" id="addInput" placeholder="輸入代號，例：2330 或 3550.TWO"
        onkeydown="if(event.key==='Enter')addStock(${curGroup})">
      <button class="add-input-btn" onclick="addStock(${curGroup})">＋</button>
    </div>
    <div id="stockList${curGroup}">
  `;
  if (!g.stocks || g.stocks.length === 0) {
    html += `<div class="empty-hint">尚無股票<br>輸入代號後按 ＋ 新增</div>`;
  } else {
    html += renderCards(g.stocks, curGroup);
  }
  html += '</div>';
  document.getElementById('mainContent').innerHTML = html;
}

function renderCards(stocks, gi) {
  return stocks.map((s, si) => {
    const hasData = s.daily;
    if (!hasData) {
      return `<div class="card">
        <div class="card-main">
          <div class="stock-id">${s.id}</div>
          <div class="signals"><div style="color:var(--muted);font-size:12px">— 尚未查詢 —</div></div>
          <button class="del-btn" onclick="removeStock(${gi},${si})">✕</button>
        </div></div>`;
    }
    const d = s.daily, w = s.weekly||{signal:'⬜',action:'空手',days:0};
    const dDays = d.days>0?`<span class="sig-days">${d.days}天</span>`:'';
    const wDays = w.days>0?`<span class="sig-days">${w.days}週</span>`:'';
    return `<div class="card">
      <div class="card-main">
        <div>
          <div class="stock-id">${s.id}</div>
        </div>
        <div class="signals">
          <div class="sig-row">
            <span class="sig-label">日</span>
            <span class="sig-badge ${sigClass(d.action)}">${d.signal} ${d.action}</span>
            ${dDays}
          </div>
          <div class="sig-row">
            <span class="sig-label">週</span>
            <span class="sig-badge ${sigClass(w.action)}">${w.signal} ${w.action}</span>
            ${wDays}
          </div>
        </div>
        <div class="price-col">
          <div class="price-val">${s.price||'—'}</div>
        </div>
        <button class="del-btn" onclick="removeStock(${gi},${si})">✕</button>
      </div>
    </div>`;
  }).join('');
}

// ── 操作 ─────────────────────────────────────────────
function switchTab(i) { curGroup = i; render(); }

function renameGroup(gi, val) {
  groups[gi].name = val.trim() || DEFAULT_GROUPS[gi];
  saveGroups(); renderTabs();
}

function addStock(gi) {
  const inp = document.getElementById('addInput');
  const id = inp.value.trim().toUpperCase();
  if (!id) return;
  if (groups[gi].stocks.find(s => s.id === id)) { alert('已有此代號'); return; }
  groups[gi].stocks.push({ id });
  saveGroups();
  inp.value = '';
  render();
}

function removeStock(gi, si) {
  groups[gi].stocks.splice(si, 1);
  saveGroups();
  render();
}

async function scanGroup(gi) {
  const stocks = groups[gi].stocks;
  if (!stocks || stocks.length === 0) { alert('請先新增股票'); return; }

  const btn = document.getElementById('scanBtn');
  btn.disabled = true; btn.textContent = '查詢中…';
  document.getElementById('stockList'+gi).innerHTML =
    '<div class="loading-row">⏳ 查詢中，請稍候…</div>';

  const ids = stocks.map(s => s.id).join(',');
  try {
    const res  = await fetch('/api/batch?ids=' + encodeURIComponent(ids));
    const data = await res.json();

    const histEntries = [];
    stocks.forEach(s => {
      const r = data[s.id];
      if (r) {
        s.price  = r.price;
        s.daily  = r.daily;
        s.weekly = r.weekly;
        histEntries.push({ id: s.id, price: r.price, daily: r.daily, weekly: r.weekly });
      }
    });

    // 寫歷史
    if (histEntries.length > 0) {
      const hist = loadHistory();
      const today = dateKey();
      let dayEntry = hist.find(h => h.date === today);
      if (!dayEntry) { dayEntry = { date: today, scans: [] }; hist.unshift(dayEntry); }
      dayEntry.scans.unshift({ time: nowStr(), group: groups[gi].name, stocks: histEntries });
      if (hist.length > 30) hist.splice(30);
      saveHistory(hist);
    }

    groups[gi].lastUpdate = '更新：' + nowStr();
    saveGroups();
    document.getElementById('updateTime'+gi).textContent = groups[gi].lastUpdate;
    document.getElementById('stockList'+gi).innerHTML = renderCards(stocks, gi);
  } catch(e) {
    document.getElementById('stockList'+gi).innerHTML =
      '<div class="loading-row" style="color:var(--red)">❌ 連線失敗，請稍後再試</div>';
  }
  btn.disabled = false; btn.textContent = '⚡ 掃描';
}

// ── 歷史面板 ─────────────────────────────────────────
function toggleHist() {
  const p = document.getElementById('histPanel');
  const isOpen = p.classList.contains('open');
  if (isOpen) { p.classList.remove('open'); return; }
  renderHistPanel();
  p.classList.add('open');
  document.getElementById('histToggle').classList.add('active');
}
function closeHistIfBg(e) {
  if (e.target === document.getElementById('histPanel')) toggleHist();
}

function renderHistPanel() {
  const hist = loadHistory();
  const body = document.getElementById('histBody');
  document.getElementById('histToggle').classList.toggle('active',
    document.getElementById('histPanel').classList.contains('open'));
  if (!hist || hist.length === 0) {
    body.innerHTML = '<div class="hist-empty">尚無歷史紀錄<br>掃描後自動記錄</div>'; return;
  }
  let html = '';
  hist.forEach(day => {
    html += `<div class="hist-day"><div class="hist-date">📅 ${day.date}</div>`;
    day.scans.forEach(scan => {
      html += `<div style="font-size:11px;color:var(--muted);padding:2px 0 4px;font-family:var(--mono)">${scan.time} · ${scan.group}</div>`;
      scan.stocks.forEach(s => {
        const d = s.daily||{}, w = s.weekly||{};
        html += `<div class="hist-row">
          <span class="hist-sid">${s.id}</span>
          <span class="hist-price">${s.price}</span>
          <span class="sig-badge ${sigClass(d.action)}" style="font-size:10px">${d.signal} 日${d.action||''}</span>
          <span class="sig-badge ${sigClass(w.action)}" style="font-size:10px">${w.signal} 週${w.action||''}</span>
        </div>`;
      });
    });
    html += '</div>';
  });
  body.innerHTML = html;
}

function clearHistory() {
  if (!confirm('確定清除所有歷史紀錄？')) return;
  saveHistory([]);
  renderHistPanel();
}

// ── 雲端同步（Google Sheet，JSONP 解決跨域）──────────────
const GAS_URL = 'https://script.google.com/macros/s/AKfycbyD6DnxV3p7j7M2PZzGarqSOBobpADkAsbVV497-YXD-FkWiyfRr55kFie2yw0B4_U8Ow/exec';

async function saveCloud() {
  const btn = document.getElementById('cloudSaveBtn');
  btn.textContent = '☁️ 儲存中…'; btn.disabled = true;
  const rows = [];
  groups.forEach((g, gi) => {
    if (g.stocks && g.stocks.length > 0) {
      g.stocks.forEach(s => rows.push([gi, g.name, s.id]));
    } else {
      rows.push([gi, g.name, '']);
    }
  });
  try {
    const res = await fetch('/api/sync-save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: rows })
    });
    const json = await res.json();
    if (json.ok) {
      btn.textContent = '✅ 已儲存';
    } else {
      btn.textContent = '❌ 失敗';
    }
    setTimeout(() => { btn.textContent = '☁️ 存雲端'; btn.disabled = false; }, 2000);
  } catch(e) {
    btn.textContent = '❌ 失敗'; btn.disabled = false;
    setTimeout(() => { btn.textContent = '☁️ 存雲端'; }, 2000);
  }
}

async function loadCloud() {
  const btn = document.getElementById('cloudLoadBtn');
  btn.textContent = '⬇️ 載入中…'; btn.disabled = true;
  try {
    const res  = await fetch('/api/sync-load', { signal: AbortSignal.timeout(20000) });
    const json = await res.json();
    const rows = json.data || [];
    if (rows.length === 0) {
      alert('雲端無資料');
      btn.textContent = '⬇️ 載雲端'; btn.disabled = false; return;
    }
    const validRows = rows.filter(r => r && String(r[2]||'').trim() !== '');
    const newGroups = DEFAULT_GROUPS.map((n, i) => ({ name: n, stocks: [] }));
    validRows.forEach(row => {
      const gi   = parseInt(row[0]);
      const name = row[1] || DEFAULT_GROUPS[gi];
      const sid  = (row[2] || '').trim().toUpperCase();
      if (gi >= 0 && gi < 5) {
        newGroups[gi].name = name;
        if (sid && !newGroups[gi].stocks.find(s => s.id === sid)) {
          newGroups[gi].stocks.push({ id: sid });
        }
      }
    });
    groups = newGroups;
    saveGroups();
    render();
    btn.textContent = '✅ 已載入';
    setTimeout(() => { btn.textContent = '⬇️ 載雲端'; btn.disabled = false; }, 2000);
    autoScanAll();
  } catch(e) {
    btn.textContent = '❌ ' + (e.message||'失敗'); btn.disabled = false;
    console.error('loadCloud error:', e);
    setTimeout(() => { btn.textContent = '⬇️ 載雲端'; btn.disabled = false; }, 4000);
  }
}

// ── 自動掃描（開啟頁面時執行）────────────────────────
async function autoScanAll() {
  for (let i = 0; i < groups.length; i++) {
    if (groups[i].stocks && groups[i].stocks.length > 0) {
      curGroup = i;
      render();
      await scanGroup(i);
    }
  }
  // 掃描完回到第一個有股票的群組
  curGroup = groups.findIndex(g => g.stocks && g.stocks.length > 0);
  if (curGroup < 0) curGroup = 0;
  render();
}

// ── 啟動 ──────────────────────────────────────────────
render();
// 開啟頁面：延遲2秒後從雲端載入（等伺服器冷啟動完成）
window.addEventListener('load', () => {
  setTimeout(() => { loadCloud(); }, 2000);
});
</script>
</body>
</html>"""


@app.route('/')
def home():
    return HTML_PAGE


if __name__ == '__main__':
    app.run()
