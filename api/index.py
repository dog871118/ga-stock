from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

def get_signal_20d(stock_id):
    try:
        if stock_id.endswith(".TWO"):
            ticker = stock_id
        else:
            ticker = stock_id + ".TW"
        df = yf.download(ticker, period="40d",
                        auto_adjust=True, progress=False)
        if df.empty or len(df) < 5:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            close = df['Close'].iloc[:, 0].dropna()
        else:
            close = df['Close'].dropna()
        close = close.iloc[-20:]
        status  = 'watching'
        buy_day = None
        for i in range(2, len(close)):
            price      = float(close.iloc[i])
            prev2_high = float(close.iloc[i-2:i].max())
            prev2_low  = float(close.iloc[i-2:i].min())
            if status == 'watching':
                if price > prev2_high:
                    status  = 'holding'
                    buy_day = i
            else:
                if price < prev2_low:
                    status  = 'watching'
                    buy_day = None
        price      = float(close.iloc[-1])
        prev2_high = float(close.iloc[-3:-1].max())
        prev2_low  = float(close.iloc[-3:-1].min())
        if status == 'holding':
            if price < prev2_low:
                signal, action = '🔴', '賣出'
            elif buy_day == len(close) - 1:
                signal, action = '🟢', '買進'
            else:
                signal, action = '🟡', '持有'
            hold_days = (len(close) - 1) - buy_day if buy_day is not None else 0
        else:
            if price > prev2_high:
                signal, action = '🟢', '買進'
            else:
                signal, action = '⬜', '空手'
            hold_days = 0
        return {
            'signal':    signal,
            'action':    action,
            'price':     round(price, 2),
            'hold_days': hold_days,
        }
    except:
        return None

@app.route('/api/check', methods=['GET'])
def check_stock():
    stock_id = request.args.get('id', '')
    if not stock_id:
        return jsonify({'error': '請輸入股票代號'}), 400
    result = get_signal_20d(stock_id)
    if result is None:
        return jsonify({'error': '查無資料，請確認代號'}), 404
    return jsonify(result)

@app.route('/api/batch', methods=['GET'])
def batch_check():
    ids = request.args.get('ids', '')
    if not ids:
        return jsonify({'error': '請輸入股票代號'}), 400
    stock_list = [s.strip() for s in ids.split(',') if s.strip()]
    results = {}
    for stock_id in stock_list:
        results[stock_id] = get_signal_20d(stock_id)
    return jsonify(results)

@app.route('/')
def home():
    return '''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GA 買賣訊號</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #0f172a; color: #e2e8f0;
  min-height: 100vh; padding: 24px 16px;
}
h1 { font-size: 1.6rem; text-align: center; color: #f8fafc; margin-bottom: 4px; }
.subtitle { text-align: center; color: #64748b; font-size: 0.85rem; margin-bottom: 24px; }
.tabs { display: flex; gap: 6px; overflow-x: auto; margin-bottom: 16px; padding-bottom: 4px; }
.tab {
  flex-shrink: 0; padding: 8px 14px; border-radius: 20px;
  border: 1px solid #334155; background: #1e293b; color: #94a3b8;
  cursor: pointer; font-size: 0.85rem; white-space: nowrap; transition: all 0.2s;
}
.tab.active { background: #6366f1; border-color: #6366f1; color: white; font-weight: 600; }
.panel { display: none; }
.panel.active { display: block; }
.card { background: #1e293b; border-radius: 14px; padding: 20px; margin-bottom: 16px; }
.group-header { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.group-name-input {
  flex: 1; background: #0f172a; border: 1px solid #334155;
  border-radius: 8px; padding: 8px 12px; color: #f1f5f9;
  font-size: 1rem; font-weight: 600;
}
.group-name-input:focus { outline: none; border-color: #6366f1; }
.btn { padding: 9px 16px; border-radius: 8px; border: none; cursor: pointer; font-size: 0.85rem; font-weight: 600; transition: background 0.2s; }
.btn-primary { background: #6366f1; color: white; }
.btn-primary:hover { background: #4f46e5; }
.btn-success { background: #10b981; color: white; }
.btn-success:hover { background: #059669; }
.btn-danger { background: transparent; border: 1px solid #ef4444; color: #ef4444; font-size: 0.75rem; padding: 4px 8px; border-radius: 6px; }
.btn-danger:hover { background: #ef4444; color: white; }
.add-row { display: flex; gap: 8px; margin-bottom: 16px; }
.add-row input {
  flex: 1; background: #0f172a; border: 1px solid #334155;
  border-radius: 8px; padding: 9px 12px; color: #f1f5f9; font-size: 0.9rem;
}
.add-row input:focus { outline: none; border-color: #6366f1; }
.stock-list { margin-bottom: 16px; }
.stock-row { display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid #0f172a; gap: 10px; }
.stock-row:last-child { border-bottom: none; }
.stock-id { font-weight: 600; color: #f1f5f9; min-width: 70px; }
.stock-signal { font-size: 1.3rem; }
.stock-action { font-size: 0.9rem; font-weight: 600; min-width: 36px; }
.stock-price { color: #94a3b8; font-size: 0.85rem; flex: 1; }
.stock-days { color: #64748b; font-size: 0.8rem; min-width: 50px; text-align: right; }
.signal-green { color: #4ade80; }
.signal-yellow { color: #facc15; }
.signal-red { color: #f87171; }
.signal-white { color: #94a3b8; }
.empty-hint { color: #475569; font-size: 0.85rem; text-align: center; padding: 20px 0; }
.loading-row { color: #64748b; font-size: 0.85rem; padding: 8px 0; text-align: center; }
.scan-btn-row { display: flex; justify-content: flex-end; }
.updated-time { color: #475569; font-size: 0.75rem; text-align: right; margin-top: 8px; }
</style>
</head>
<body>
<h1>📈 GA 買賣訊號</h1>
<p class="subtitle">2日高低點突破系統</p>
<div class="tabs" id="tabs"></div>
<div id="panels"></div>
<script>
const DEFAULT_GROUPS = [
  { name: "短線強勢股", stocks: [] },
  { name: "波段持股", stocks: [] },
  { name: "觀察名單", stocks: [] },
  { name: "自選群組4", stocks: [] },
  { name: "自選群組5", stocks: [] }
];
function loadGroups() {
  try {
    const saved = localStorage.getItem("ga_groups");
    return saved ? JSON.parse(saved) : DEFAULT_GROUPS;
  } catch(e) { return DEFAULT_GROUPS; }
}
function saveGroups() { localStorage.setItem("ga_groups", JSON.stringify(groups)); }
let groups = loadGroups();
let activeTab = 0;

function render() {
  const tabsEl = document.getElementById("tabs");
  const panelsEl = document.getElementById("panels");
  tabsEl.innerHTML = "";
  panelsEl.innerHTML = "";
  groups.forEach((g, i) => {
    const tab = document.createElement("div");
    tab.className = "tab" + (i === activeTab ? " active" : "");
    tab.textContent = g.name || ("群組" + (i+1));
    tab.onclick = () => { activeTab = i; render(); };
    tabsEl.appendChild(tab);
    const panel = document.createElement("div");
    panel.className = "panel" + (i === activeTab ? " active" : "");
    panel.innerHTML = `
      <div class="card">
        <div class="group-header">
          <input class="group-name-input" value="${g.name}" placeholder="群組名稱"
            onchange="renameGroup(${i}, this.value)">
        </div>
        <div class="add-row">
          <input type="text" id="addInput${i}" placeholder="輸入代號，如 2330 或 3550.TWO" maxlength="12"
            onkeydown="if(event.key==='Enter') addStock(${i})">
          <button class="btn btn-primary" onclick="addStock(${i})">新增</button>
        </div>
        <div class="stock-list" id="stockList${i}">${renderStockRows(g.stocks, i, false)}</div>
        <div class="scan-btn-row">
          <button class="btn btn-success" onclick="scanGroup(${i})">🔍 掃描訊號</button>
        </div>
        <div class="updated-time" id="updatedTime${i}"></div>
      </div>`;
    panelsEl.appendC
