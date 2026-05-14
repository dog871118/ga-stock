from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

# ────────────────────────────────────────────
#  訊號計算
# ────────────────────────────────────────────
def calc_signal(close_series):
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
    if stock_id.endswith(".TW") or stock_id.endswith(".TWO"):
        return stock_id
    t = stock_id + ".TW"
    try:
        df = yf.download(t, period="5d", auto_adjust=True, progress=False)
        if not df.empty and len(df) >= 1:
            return t
    except:
        pass
    return stock_id + ".TWO"


def get_signals(stock_id):
    try:
        ticker = resolve_ticker(stock_id)

        # 日線
        df_d = yf.download(ticker, period="60d", auto_adjust=True, progress=False)
        if df_d.empty or len(df_d) < 5:
            return None
        if isinstance(df_d.columns, pd.MultiIndex):
            close_d = df_d['Close'].iloc[:, 0].dropna()
        else:
            close_d = df_d['Close'].dropna()

        price = round(float(close_d.iloc[-1]), 2)
        ma5   = round(float(close_d.iloc[-5:].mean()),  2) if len(close_d) >= 5  else None
        ma10  = round(float(close_d.iloc[-10:].mean()), 2) if len(close_d) >= 10 else None

        d_signal, d_action, d_days = calc_signal(close_d.iloc[-20:])

        # 週線
        df_w = yf.download(ticker, period="60wk", interval="1wk", auto_adjust=True, progress=False)
        if df_w.empty or len(df_w) < 5:
            w_signal, w_action, w_days = '⬜', '空手', 0
        else:
            if isinstance(df_w.columns, pd.MultiIndex):
                close_w = df_w['Close'].iloc[:, 0].dropna()
            else:
                close_w = df_w['Close'].dropna()
            w_signal, w_action, w_days = calc_signal(close_w.iloc[-20:])

        # 60分K 240均線
        ma60k240 = None
        try:
            df60 = yf.download(ticker, period="60d", interval="60m", auto_adjust=True, progress=False)
            if not df60.empty:
                if isinstance(df60.columns, pd.MultiIndex):
                    c60 = df60['Close'].iloc[:, 0].dropna()
                else:
                    c60 = df60['Close'].dropna()
                if len(c60) >= 240:
                    ma60k240 = round(float(c60.iloc[-240:].mean()), 2)
                elif len(c60) >= 20:
                    ma60k240 = round(float(c60.mean()), 2)
        except:
            pass

        return {
            'price':    price,
            'ma5':      ma5,
            'ma10':     ma10,
            'ma60k240': ma60k240,
            'daily':    {'signal': d_signal, 'action': d_action, 'days': d_days},
            'weekly':   {'signal': w_signal, 'action': w_action, 'days': w_days},
        }
    except:
        return None


# ────────────────────────────────────────────
#  API
# ────────────────────────────────────────────
@app.route('/api/check', methods=['GET'])
def check_stock():
    stock_id = request.args.get('id', '').strip().upper()
    if not stock_id:
        return jsonify({'error': '請輸入股票代號'}), 400
    result = get_signals(stock_id)
    if result is None:
        return jsonify({'error': '查無資料'}), 404
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
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>GA 股票訊號</title>
<style>
:root {
  --bg:      #0d1b2a;
  --surface: #132338;
  --card:    #1a2f45;
  --border:  #1e3a5f;
  --text:    #e2e8f0;
  --muted:   #4a6fa5;
  --accent:  #38bdf8;
  --green:   #34c759;
  --yellow:  #ffd60a;
  --red:     #ff453a;
  --radius:  10px;
  --mono:    'Menlo', 'Consolas', monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: var(--bg); color: var(--text); font-family: -apple-system, sans-serif; min-height: 100vh; }

/* header */
.header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(13,27,42,0.95);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  padding: 10px 14px 8px;
}
.header-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.logo { font-family: var(--mono); font-size: 14px; color: var(--accent); letter-spacing: 2px; font-weight: 700; }
.top-btns { display: flex; gap: 5px; }
.top-btn {
  font-size: 11px; padding: 4px 10px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; color: var(--muted); cursor: pointer; white-space: nowrap;
  transition: all .15s;
}
.top-btn:hover { border-color: var(--accent); color: var(--accent); }
.top-btn:disabled { opacity: .5; cursor: default; }

/* tabs */
.tabs { display: flex; gap: 5px; overflow-x: auto; scrollbar-width: none; padding-bottom: 1px; }
.tabs::-webkit-scrollbar { display: none; }
.tab {
  flex-shrink: 0; padding: 4px 12px; border-radius: 14px; font-size: 12px;
  border: 1px solid var(--border); background: transparent;
  color: var(--muted); cursor: pointer; transition: all .15s; white-space: nowrap;
}
.tab.active { background: var(--accent); border-color: var(--accent); color: #000; font-weight: 700; }

/* main */
.main { padding: 12px 12px 80px; max-width: 520px; margin: 0 auto; }

/* group header */
.grp-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.grp-name {
  flex: 1; background: transparent; border: none;
  border-bottom: 1px dashed var(--border);
  color: var(--text); font-size: 14px; font-weight: 700;
  padding: 2px 0; font-family: inherit;
}
.grp-name:focus { outline: none; border-bottom-color: var(--accent); }
.scan-btn {
  padding: 5px 14px; background: var(--accent); color: #000;
  border: none; border-radius: 14px; font-size: 12px; font-weight: 700;
  cursor: pointer; white-space: nowrap;
}
.scan-btn:disabled { background: var(--border); color: var(--muted); cursor: default; }
.update-time { font-size: 10px; color: var(--muted); margin-bottom: 6px; font-family: var(--mono); }

/* add row */
.add-row { display: flex; gap: 6px; margin-bottom: 10px; }
.add-input {
  flex: 1; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 8px 10px;
  color: var(--text); font-size: 13px; font-family: var(--mono);
}
.add-input::placeholder { color: var(--muted); }
.add-input:focus { outline: none; border-color: var(--accent); }
.add-btn {
  padding: 8px 14px; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); color: var(--accent); font-size: 16px; cursor: pointer;
}
.add-btn:hover { background: var(--accent); color: #000; }

/* 表格標題 */
.tbl-head {
  display: grid;
  grid-template-columns: 52px 58px 1fr 68px 68px 68px 22px;
  gap: 4px;
  padding: 4px 10px;
  font-size: 10px; color: var(--muted);
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}

/* card */
.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); margin-bottom: 6px;
  display: grid;
  grid-template-columns: 52px 58px 1fr 68px 68px 68px 22px;
  gap: 4px;
  align-items: center;
  padding: 8px 10px;
  transition: border-color .15s;
}
.card:hover { border-color: var(--muted); }

.c-id { font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--accent); }
.c-price { font-family: var(--mono); font-size: 14px; font-weight: 600; color: var(--text); }

/* signals */
.sigs { display: flex; flex-direction: column; gap: 3px; }
.sig-row { display: flex; align-items: center; gap: 4px; }
.sig-lbl { font-size: 9px; color: var(--muted); width: 14px; font-family: var(--mono); }
.sig-badge {
  font-size: 11px; padding: 1px 7px; border-radius: 8px; font-weight: 700;
}
.sig-green  { background: rgba(52,199,89,.18);  color: var(--green); }
.sig-yellow { background: rgba(255,214,10,.15); color: var(--yellow); }
.sig-red    { background: rgba(255,69,58,.15);  color: var(--red); }
.sig-gray   { background: rgba(74,111,165,.15); color: var(--muted); }
.sig-days { font-size: 10px; color: var(--muted); font-family: var(--mono); }

/* ma values */
.c-ma {
  font-family: var(--mono); font-size: 12px; text-align: right;
}
.ma-up   { color: var(--green); }
.ma-down { color: var(--red); }
.ma-na   { color: var(--muted); }

.del-btn {
  background: none; border: none; color: var(--muted);
  cursor: pointer; font-size: 14px; text-align: center; line-height: 1;
}
.del-btn:hover { color: var(--red); }

.loading { padding: 16px; text-align: center; color: var(--muted); font-size: 12px; }
.empty   { padding: 28px; text-align: center; color: var(--muted); font-size: 12px; line-height: 2; }

/* history panel */
.hist-panel {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,.65); backdrop-filter: blur(4px);
  display: none; align-items: flex-end;
}
.hist-panel.open { display: flex; }
.hist-inner {
  width: 100%; max-width: 520px; margin: 0 auto;
  background: var(--surface); border-radius: 16px 16px 0 0;
  border: 1px solid var(--border); max-height: 72vh;
  display: flex; flex-direction: column;
}
.hist-hdr {
  padding: 14px 16px 8px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.hist-title { font-size: 14px; font-weight: 700; }
.hist-close { background: none; border: none; color: var(--muted); font-size: 20px; cursor: pointer; }
.hist-body  { overflow-y: auto; padding: 6px 0; }
.hist-date  { font-size: 10px; font-family: var(--mono); color: var(--accent); padding: 8px 14px 4px; }
.hist-row   {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 14px; border-bottom: 1px solid rgba(30,58,95,.4);
  font-size: 12px;
}
.hist-sid   { font-family: var(--mono); color: var(--accent); min-width: 46px; }
.hist-price { font-family: var(--mono); min-width: 48px; }
.hist-empty { padding: 20px; text-align: center; color: var(--muted); font-size: 12px; }
.hist-clear {
  margin: 6px 14px; padding: 7px; background: none;
  border: 1px solid var(--border); border-radius: var(--radius);
  color: var(--muted); cursor: pointer; font-size: 11px; width: calc(100% - 28px);
}
.hist-clear:hover { border-color: var(--red); color: var(--red); }
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div class="logo">GA.STOCK</div>
    <div class="top-btns">
      <button class="top-btn" id="btnLoad" onclick="loadCloud()">⬇️ 載雲端</button>
      <button class="top-btn" id="btnSave" onclick="saveCloud()">☁️ 存雲端</button>
      <button class="top-btn" id="btnHist" onclick="toggleHist()">📋 歷史</button>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
</div>

<div class="main" id="main"></div>

<div class="hist-panel" id="histPanel" onclick="closeHistBg(event)">
  <div class="hist-inner">
    <div class="hist-hdr">
      <div class="hist-title">掃描歷史</div>
      <button class="hist-close" onclick="toggleHist()">×</button>
    </div>
    <div class="hist-body" id="histBody"></div>
    <button class="hist-clear" onclick="clearHist()">🗑 清除歷史</button>
  </div>
</div>

<script>
const GROUPS_KEY  = 'ga_g_v4';
const HISTORY_KEY = 'ga_h_v4';
const DEF_NAMES   = ['短線強勢股','波段持股','觀察名單','自選群組4','自選群組5'];

function loadGroups() {
  try {
    const d = JSON.parse(localStorage.getItem(GROUPS_KEY));
    if (d && d.length === 5) return d;
  } catch(e){}
  return DEF_NAMES.map(n => ({ name: n, stocks: [] }));
}
function saveGroups() { localStorage.setItem(GROUPS_KEY, JSON.stringify(groups)); }
function loadHist()   { try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch(e){ return []; } }
function saveHist(h)  { localStorage.setItem(HISTORY_KEY, JSON.stringify(h)); }

let groups   = loadGroups();
let curGroup = 0;

function sigClass(action) {
  return action==='買進'?'sig-green': action==='持有'?'sig-yellow': action==='賣出'?'sig-red':'sig-gray';
}
function maClass(price, ma) {
  if (!ma || !price) return 'ma-na';
  return price >= ma ? 'ma-up' : 'ma-down';
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

function renderTabs() {
  document.getElementById('tabs').innerHTML = groups.map((g,i) =>
    `<button class="tab${i===curGroup?' active':''}" onclick="switchTab(${i})">${g.name}</button>`
  ).join('');
}

function render() {
  renderTabs();
  const g = groups[curGroup];
  let html = `
    <div class="grp-head">
      <input class="grp-name" value="${g.name}"
        onchange="renameGroup(${curGroup},this.value)"
        onblur="renameGroup(${curGroup},this.value)">
      <button class="scan-btn" id="scanBtn" onclick="scanGroup(${curGroup})">⚡ 掃描</button>
    </div>
    <div class="update-time" id="upTime">${g.lastUpdate||''}</div>
    <div class="add-row">
      <input class="add-input" id="addInput" placeholder="輸入代號，如 2330 或 3624"
        onkeydown="if(event.key==='Enter')addStock(${curGroup})">
      <button class="add-btn" onclick="addStock(${curGroup})">＋</button>
    </div>
  `;

  if (!g.stocks || g.stocks.length === 0) {
    html += `<div class="empty">尚無股票<br>輸入代號按 ＋ 新增</div>`;
  } else {
    html += `<div class="tbl-head">
      <span>代號</span><span>收盤價</span><span>訊號／天數</span>
      <span style="text-align:right">60MA240</span>
      <span style="text-align:right">MA5</span>
      <span style="text-align:right">MA10</span>
      <span></span>
    </div>`;
    html += g.stocks.map((s, si) => renderCard(s, curGroup, si)).join('');
  }
  document.getElementById('main').innerHTML = html;
}

function renderCard(s, gi, si) {
  if (!s.daily) {
    return `<div class="card">
      <span class="c-id">${s.id}</span>
      <span class="c-price">—</span>
      <span style="color:var(--muted);font-size:11px">尚未查詢</span>
      <span class="c-ma ma-na">—</span>
      <span class="c-ma ma-na">—</span>
      <span class="c-ma ma-na">—</span>
      <button class="del-btn" onclick="removeStock(${gi},${si})">✕</button>
    </div>`;
  }
  const d  = s.daily;
  const w  = s.weekly || {signal:'⬜',action:'空手',days:0};
  const dDays = d.days > 0 ? `<span class="sig-days">${d.days}天</span>` : '';
  const wDays = w.days > 0 ? `<span class="sig-days">${w.days}週</span>` : '';
  const ma60  = s.ma60k240 ? `<span class="c-ma ${maClass(s.price, s.ma60k240)}">${s.ma60k240}</span>` : `<span class="c-ma ma-na">—</span>`;
  const ma5v  = s.ma5      ? `<span class="c-ma ${maClass(s.price, s.ma5)}">${s.ma5}</span>`           : `<span class="c-ma ma-na">—</span>`;
  const ma10v = s.ma10     ? `<span class="c-ma ${maClass(s.price, s.ma10)}">${s.ma10}</span>`         : `<span class="c-ma ma-na">—</span>`;
  return `<div class="card">
    <span class="c-id">${s.id}</span>
    <span class="c-price">${s.price}</span>
    <div class="sigs">
      <div class="sig-row">
        <span class="sig-lbl">日</span>
        <span class="sig-badge ${sigClass(d.action)}">${d.signal} ${d.action}</span>
        ${dDays}
      </div>
      <div class="sig-row">
        <span class="sig-lbl">週</span>
        <span class="sig-badge ${sigClass(w.action)}">${w.signal} ${w.action}</span>
        ${wDays}
      </div>
    </div>
    ${ma60}${ma5v}${ma10v}
    <button class="del-btn" onclick="removeStock(${gi},${si})">✕</button>
  </div>`;
}

function switchTab(i) { curGroup = i; render(); }

function renameGroup(gi, val) {
  groups[gi].name = val.trim() || DEF_NAMES[gi];
  saveGroups(); renderTabs();
}

function addStock(gi) {
  const inp = document.getElementById('addInput');
  const id  = inp.value.trim().toUpperCase();
  if (!id) return;
  if (groups[gi].stocks.find(s => s.id === id)) { alert('已有此代號'); return; }
  groups[gi].stocks.push({ id });
  saveGroups(); inp.value = ''; render();
}

function removeStock(gi, si) {
  groups[gi].stocks.splice(si, 1);
  saveGroups(); render();
}

async function scanGroup(gi) {
  const stocks = groups[gi].stocks;
  if (!stocks || stocks.length === 0) { alert('請先新增股票'); return; }
  const btn = document.getElementById('scanBtn');
  btn.disabled = true; btn.textContent = '查詢中…';
  document.getElementById('main').querySelector(`#scanBtn`) && null;

  const ids = stocks.map(s => s.id).join(',');
  try {
    const res  = await fetch('/api/batch?ids=' + encodeURIComponent(ids));
    const data = await res.json();
    const histStocks = [];
    stocks.forEach(s => {
      const r = data[s.id];
      if (r) {
        s.price    = r.price;
        s.ma5      = r.ma5;
        s.ma10     = r.ma10;
        s.ma60k240 = r.ma60k240;
        s.daily    = r.daily;
        s.weekly   = r.weekly;
        histStocks.push({ id: s.id, price: r.price, daily: r.daily, weekly: r.weekly });
      }
    });
    if (histStocks.length > 0) {
      const hist    = loadHist();
      const today   = dateKey();
      let dayEntry  = hist.find(h => h.date === today);
      if (!dayEntry) { dayEntry = { date: today, scans: [] }; hist.unshift(dayEntry); }
      dayEntry.scans.unshift({ time: nowStr(), group: groups[gi].name, stocks: histStocks });
      if (hist.length > 30) hist.splice(30);
      saveHist(hist);
    }
    groups[gi].lastUpdate = '更新：' + nowStr();
    saveGroups();
  } catch(e) { alert('連線失敗，請稍後再試'); }
  btn.disabled = false; btn.textContent = '⚡ 掃描';
  render();
}

async function autoScanAll() {
  for (let i = 0; i < groups.length; i++) {
    if (groups[i].stocks && groups[i].stocks.length > 0) {
      curGroup = i; render();
      await scanGroup(i);
    }
  }
  curGroup = groups.findIndex(g => g.stocks && g.stocks.length > 0);
  if (curGroup < 0) curGroup = 0;
  render();
}

async function saveCloud() {
  const btn = document.getElementById('btnSave');
  btn.textContent = '儲存中…'; btn.disabled = true;
  const rows = [];
  groups.forEach((g, gi) => {
    if (g.stocks && g.stocks.length > 0) {
      g.stocks.forEach(s => rows.push([gi, g.name, s.id]));
    } else {
      rows.push([gi, g.name, '']);
    }
  });
  try {
    const res  = await fetch('/api/sync-save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: rows })
    });
    const json = await res.json();
    btn.textContent = json.ok ? '✅ 已儲存' : '❌ 失敗';
  } catch(e) { btn.textContent = '❌ 失敗'; }
  setTimeout(() => { btn.textContent = '☁️ 存雲端'; btn.disabled = false; }, 2000);
}

async function loadCloud() {
  const btn = document.getElementById('btnLoad');
  btn.textContent = '載入中…'; btn.disabled = true;
  try {
    const res  = await fetch('/api/sync-load', { signal: AbortSignal.timeout(20000) });
    const json = await res.json();
    const rows = json.data || [];
    if (rows.length === 0) { alert('雲端無資料'); btn.textContent = '⬇️ 載雲端'; btn.disabled = false; return; }
    const validRows = rows.filter(r => r && String(r[2]||'').trim() !== '');
    const newGroups = DEF_NAMES.map((n, i) => ({ name: n, stocks: [] }));
    validRows.forEach(row => {
      const gi  = parseInt(row[0]);
      const nm  = row[1] || DEF_NAMES[gi];
      const sid = String(row[2]||'').trim().toUpperCase();
      if (gi >= 0 && gi < 5) {
        newGroups[gi].name = nm;
        if (sid && !newGroups[gi].stocks.find(s => s.id === sid)) {
          newGroups[gi].stocks.push({ id: sid });
        }
      }
    });
    groups = newGroups;
    saveGroups(); render();
    btn.textContent = '✅ 已載入';
    setTimeout(() => { btn.textContent = '⬇️ 載雲端'; btn.disabled = false; }, 1500);
    autoScanAll();
  } catch(e) {
    btn.textContent = '❌ ' + (e.message||'失敗'); btn.disabled = false;
    setTimeout(() => { btn.textContent = '⬇️ 載雲端'; btn.disabled = false; }, 3000);
  }
}

function toggleHist() {
  const p = document.getElementById('histPanel');
  p.classList.toggle('open');
  if (p.classList.contains('open')) renderHistPanel();
}
function closeHistBg(e) { if (e.target === document.getElementById('histPanel')) toggleHist(); }

function renderHistPanel() {
  const hist = loadHist();
  const body = document.getElementById('histBody');
  if (!hist || hist.length === 0) { body.innerHTML = '<div class="hist-empty">尚無歷史紀錄</div>'; return; }
  let html = '';
  hist.forEach(day => {
    html += `<div class="hist-date">📅 ${day.date}</div>`;
    day.scans.forEach(scan => {
      html += `<div style="font-size:10px;color:var(--muted);padding:2px 14px;font-family:var(--mono)">${scan.time} · ${scan.group}</div>`;
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
  });
  body.innerHTML = html;
}

function clearHist() {
  if (!confirm('確定清除所有歷史？')) return;
  saveHist([]); renderHistPanel();
}

// 啟動
render();
window.addEventListener('load', () => {
  setTimeout(() => loadCloud(), 2000);
});
</script>
</body>
</html>"""


@app.route('/')
def home():
    return HTML_PAGE

if __name__ == '__main__':
    app.run()
