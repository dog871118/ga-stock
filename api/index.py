# GA Stock v8 - MA20/MA60/均線買點/回踩買點/訊號異動
from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

def calc_signal(close_series):
    if len(close_series) < 5:
        return '', '空手', 0

    status   = 'watching'
    buy_day  = None
    sell_day = None

    for i in range(2, len(close_series)):
        price      = float(close_series.iloc[i])
        prev2_high = float(close_series.iloc[i-2:i].max())
        prev2_low  = float(close_series.iloc[i-2:i].min())
        if status == 'watching':
            if price > prev2_high:
                status   = 'holding'
                buy_day  = i
                sell_day = None
        else:
            if price < prev2_low:
                status   = 'watching'
                sell_day = i
                buy_day  = None

    n          = len(close_series)
    price      = float(close_series.iloc[-1])
    prev2_high = float(close_series.iloc[-3:-1].max())
    prev2_low  = float(close_series.iloc[-3:-1].min())

    if status == 'holding':
        if price < prev2_low:
            signal, action = '', '賣出'
        elif buy_day == n - 1:
            signal, action = '', '買進'
        else:
            signal, action = '', '持有'
        hold_days = (n - 1) - buy_day if buy_day is not None else 0
    else:
        if sell_day == n - 1:
            signal, action = '', '賣出'
        elif price > prev2_high:
            signal, action = '', '買進'
        else:
            signal, action = '', '空手'
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
        df_d = yf.download(ticker, period="60d", auto_adjust=True, progress=False)
        if df_d.empty or len(df_d) < 5:
            return None
        if isinstance(df_d.columns, pd.MultiIndex):
            close_d = df_d['Close'].iloc[:, 0].dropna()
        else:
            close_d = df_d['Close'].dropna()
        # 台股週一~五 09:00~13:30為交易時間
        # 盤中（且最後一筆是今天）才去掉未收盤K棒
        from datetime import datetime, date
        import pytz
        now_tw = datetime.now(pytz.timezone('Asia/Taipei'))
        today_tw = now_tw.date()
        last_date = close_d.index[-1]
        if hasattr(last_date, 'date'):
            last_date = last_date.date()
        is_today = (last_date == today_tw)
        is_trading = (now_tw.weekday() < 5) and (
            (now_tw.hour == 9 and now_tw.minute >= 0) or
            (9 < now_tw.hour < 13) or
            (now_tw.hour == 13 and now_tw.minute < 30)
        )
        if is_today and is_trading and len(close_d) > 1:
            close_d = close_d.iloc[:-1]

        price = round(float(close_d.iloc[-1]), 2)
        ma5   = round(float(close_d.iloc[-5:].mean()),  2) if len(close_d) >= 5  else None
        ma10  = round(float(close_d.iloc[-10:].mean()), 2) if len(close_d) >= 10 else None
        ma20  = round(float(close_d.iloc[-20:].mean()), 2) if len(close_d) >= 20 else None
        ma60d = round(float(close_d.iloc[-60:].mean()), 2) if len(close_d) >= 60 else None
        d_signal, d_action, d_days = calc_signal(close_d.iloc[-20:])
        # 昨日訊號
        if len(close_d) >= 6:
            y_signal, y_action, _ = calc_signal(close_d.iloc[-21:-1])
        else:
            y_signal, y_action = '', ''
        # 創10日新高
        new_high_10 = False
        if len(close_d) >= 10:
            new_high_10 = float(price) >= float(close_d.iloc[-10:].max())

        df_w = yf.download(ticker, period="60wk", interval="1wk", auto_adjust=True, progress=False)
        if df_w.empty or len(df_w) < 5:
            w_signal, w_action, w_days = '⬜', '空手', 0
        else:
            if isinstance(df_w.columns, pd.MultiIndex):
                close_w = df_w['Close'].iloc[:, 0].dropna()
            else:
                close_w = df_w['Close'].dropna()
            w_signal, w_action, w_days = calc_signal(close_w.iloc[-20:])

        ma60k240 = None
        try:
            df60 = yf.download(ticker, period="60d", interval="60m", auto_adjust=True, progress=False)
            if not df60.empty:
                if isinstance(df60.columns, pd.MultiIndex):
                    c60 = df60['Close'].iloc[:, 0].dropna()
                else:
                    c60 = df60['Close'].dropna()
                if len(c60) >= 20:
                    ma60k240 = round(float(c60.iloc[-min(240,len(c60)):].mean()), 2)
        except:
            pass

        # 抓股名
        stock_name = ''
        try:
            sid = stock_id.replace('.TW','').replace('.TWO','')
            if twstock and sid in twstock.codes:
                stock_name = twstock.codes[sid].name
        except:
            pass

        # 昨日收盤價
        prev_price = round(float(close_d.iloc[-2]), 2) if len(close_d) >= 2 else None

        # 接近均線判斷（3%以內）
        def near(p, ma):
            if p and ma:
                return abs(p - ma) / ma <= 0.03
            return False

        return {
            'price':      price,
            'prev_price': prev_price,
            'name':       stock_name,
            'ma5':        ma5,
            'ma10':       ma10,
            'ma20':       ma20,
            'ma60d':      ma60d,
            'ma60k240':   ma60k240,
            'near_ma5':   near(price, ma5),
            'near_ma10':  near(price, ma10),
            'near_ma20':  near(price, ma20),
            'near_ma60d': near(price, ma60d),
            'near_ma60':  near(price, ma60k240),
            'daily':      {'signal': d_signal, 'action': d_action, 'days': d_days},
            'yesterday':  {'signal': y_signal, 'action': y_action},
            'new_high_10': new_high_10,
            'weekly':     {'signal': w_signal, 'action': w_action, 'days': w_days},
        }
    except:
        return None


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
try:
    import twstock
except:
    twstock = None
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


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>GA 股票訊號</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html, body {
  background: #0d1b2a;
  color: #ffffff;
  font-family: -apple-system, 'SF Pro Text', sans-serif;
  min-height: 100vh;
  font-size: 15px;
}
.hdr {
  position: sticky; top: 0; z-index: 100;
  background: #0d1b2a;
  border-bottom: 1px solid #1e3a5f;
  padding: 10px 14px 0;
}
.hdr-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.logo { font-size: 16px; font-weight: 800; color: #38bdf8; letter-spacing: 1px; }
.hdr-btns { display: flex; gap: 6px; }
.hbtn {
  font-size: 12px; padding: 5px 11px;
  border: 1px solid #2d5480; border-radius: 20px;
  background: transparent; color: #ffffff; cursor: pointer;
}
.hbtn:active { background: #1e3a5f; }
.hbtn:disabled { opacity: .4; }
.tabs { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; padding-bottom: 0; }
.tabs::-webkit-scrollbar { display: none; }
.tab {
  flex-shrink: 0; padding: 7px 14px 8px;
  font-size: 13px; font-weight: 500;
  color: #ffffff; cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap; background: none;
  border-top: none; border-left: none; border-right: none;
}
.tab.active { color: #38bdf8; border-bottom-color: #38bdf8; font-weight: 700; }
.main { padding: 12px 0 80px; max-width: 540px; margin: 0 auto; }
.grp-bar { display: flex; align-items: center; gap: 8px; padding: 0 14px; margin-bottom: 4px; }
.grp-name-inp {
  flex: 1; background: transparent; border: none;
  color: #ffffff; font-size: 16px; font-weight: 700;
  padding: 4px 0; font-family: inherit;
  border-bottom: 1px dashed #2d5480;
}
.grp-name-inp:focus { outline: none; border-bottom-color: #38bdf8; }
.scan-btn {
  padding: 6px 16px; background: #38bdf8; color: #000;
  border: none; border-radius: 20px; font-size: 13px; font-weight: 700; cursor: pointer;
}
.scan-btn:disabled { background: #1e3a5f; color: #ffffff; cursor: default; }
.upd-time { font-size: 12px; color: #38bdf8; padding: 0 14px 8px; }
.add-row { display: flex; gap: 8px; padding: 0 14px 10px; }
.add-inp {
  flex: 1; background: #132338; border: 1px solid #1e3a5f;
  border-radius: 10px; padding: 9px 12px;
  color: #ffffff; font-size: 14px;
}
.add-inp::placeholder { color: #7aa8d0; }
.add-inp:focus { outline: none; border-color: #38bdf8; }
.add-btn {
  width: 42px; background: #132338; border: 1px solid #1e3a5f;
  border-radius: 10px; color: #38bdf8; font-size: 22px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.tbl-hdr {
  display: flex; align-items: center;
  padding: 4px 14px; border-bottom: 1px solid #1e3a5f; margin-bottom: 2px;
}
.tbl-hdr span { font-size: 12px; color: #38bdf8; }
.col-id    { width: 70px; }
.col-price { width: 56px; text-align: right; }
.col-sig   { flex: 1; padding-left: 10px; }
.col-del   { width: 24px; }
.row {
  display: flex; align-items: center;
  padding: 11px 14px; border-bottom: 1px solid #132338;
}
.row:active { background: #132338; }
.r-id-wrap { width: 70px; display: flex; flex-direction: column; gap: 2px; }
.r-id { font-size: 16px; font-weight: 700; color: #38bdf8; font-variant-numeric: tabular-nums; }
.r-name { font-size: 14px; color: #ffd60a; white-space: nowrap; }
.r-price {
  width: 56px; text-align: right;
  font-size: 16px; font-weight: 600; color: #ffd60a;
  font-variant-numeric: tabular-nums;
}
.r-mid { flex: 1; padding-left: 10px; display: flex; flex-direction: column; gap: 4px; }
.sig-line { display: flex; align-items: baseline; gap: 5px; }
.sig-lbl  { font-size: 13px; color: #38bdf8; width: 16px; flex-shrink: 0; }
.sig-txt  { font-size: 15px; font-weight: 700; }
.sig-days { font-size: 13px; color: #ff9f0a; font-weight: 600; }
.ma-row   { display: flex; gap: 10px; }
.ma-item  { display: flex; flex-direction: column; align-items: flex-start; }
.ma-val   { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.ma-lbl   { font-size: 11px; color: #38bdf8; }
.c-buy  { color: #34c759; }
.c-hold { color: #ffd60a; }
.c-sell { color: #ff453a; }
.c-idle { color: #ffffff; }
.ma-up  { color: #34c759; }
.ma-dn  { color: #ff453a; }
.ma-na  { color: #ffffff; }
.r-del {
  width: 24px; text-align: right;
  background: none; border: none;
  color: #ffffff; font-size: 16px; cursor: pointer; padding: 2px;
  align-self: flex-start; margin-top: 2px;
}
.r-del:active { color: #ff453a; }
.empty { padding: 40px 14px; text-align: center; color: #ffffff; font-size: 14px; line-height: 2.2; }
.loading { padding: 20px 14px; text-align: center; color: #ffffff; font-size: 13px; }
.hist-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,.6);
  display: none; align-items: flex-end;
}
.hist-overlay.open { display: flex; }
.hist-sheet {
  width: 100%; max-width: 540px; margin: 0 auto;
  background: #132338; border-radius: 18px 18px 0 0;
  border-top: 1px solid #1e3a5f;
  max-height: 70vh; display: flex; flex-direction: column;
}
.hist-top {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px 10px; border-bottom: 1px solid #1e3a5f;
}
.hist-title { font-size: 15px; font-weight: 700; color: #ffffff; }
.hist-x { background: none; border: none; color: #ffffff; font-size: 22px; cursor: pointer; }
.hist-list { overflow-y: auto; flex: 1; }
.h-date { font-size: 11px; color: #38bdf8; padding: 10px 16px 4px; }
.h-meta { font-size: 11px; color: #ffffff; padding: 0 16px 4px; }
.h-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 16px; border-bottom: 1px solid #0d1b2a; font-size: 13px;
}
.h-id    { color: #38bdf8; width: 46px; font-weight: 600; }
.h-price { color: #ffffff; width: 50px; text-align: right; font-variant-numeric: tabular-nums; }
.hist-none { padding: 24px; text-align: center; color: #ffffff; font-size: 13px; }
.hist-clr {
  margin: 8px 14px; padding: 9px;
  border: 1px solid #1e3a5f; border-radius: 10px;
  background: none; color: #ffffff; font-size: 12px; cursor: pointer;
  width: calc(100% - 28px);
}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-top">
    <div class="logo">GA.STOCK</div>
    <div class="hdr-btns">
      <button class="hbtn" id="btnLoad" onclick="loadCloud()">⬇ 載雲端</button>
      <button class="hbtn" id="btnSave" onclick="saveCloud()">↑ 存雲端</button>
      <button class="hbtn" onclick="toggleHist()">≡ 歷史</button>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
</div>

<div class="main" id="main"></div>

<div class="hist-overlay" id="histOverlay" onclick="closeHistBg(event)">
  <div class="hist-sheet">
    <div class="hist-top">
      <span class="hist-title">掃描歷史</span>
      <button class="hist-x" onclick="toggleHist()">×</button>
    </div>
    <div class="hist-list" id="histList"></div>
    <button class="hist-clr" onclick="clearHist()">清除所有歷史</button>
  </div>
</div>

<script>
const GK = 'ga_g_v5', HK = 'ga_h_v5', SK = 'ga_sig_v5';
const DN = ['短線強勢股','波段持股','觀察名單','自選群組4','自選群組5'];
const SPECIAL_GROUPS = [
  { name: '均線買點', idx: 5 },
  { name: '回踩買點', idx: 6 },
  { name: '訊號異動', idx: 7 },
];

function lgr() {
  try { const d=JSON.parse(localStorage.getItem(GK)); if(d&&d.length===5) return d; } catch(e){}
  return DN.map(n=>({name:n,stocks:[]}));
}
function allGroups() {
  return [
    ...groups,
    { name:'均線買點', stocks:[], special:'near' },
    { name:'回踩買點', stocks:[], special:'down' },
    { name:'訊號異動', stocks:[], special:'change' },
    { name:'創新高', stocks:[], special:'newhigh' },
  ];
}
function sgr() { localStorage.setItem(GK,JSON.stringify(groups)); }
function lhi() { try { return JSON.parse(localStorage.getItem(HK))||[]; } catch(e){ return []; } }
function shi(h){ localStorage.setItem(HK,JSON.stringify(h)); }

let groups=lgr(), cur=0;

function sigColor(a){ return a==='買進'?'c-buy':a==='持有'?'c-hold':a==='賣出'?'c-sell':'c-idle'; }
function maColor(p,m){ if(!m||!p) return 'ma-na'; return p>=m?'ma-up':'ma-dn'; }
function ts(){
  const d=new Date();
  return d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate()+' '+d.getHours()+':'+String(d.getMinutes()).padStart(2,'0');
}
function dk(){
  const d=new Date();
  return d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate();
}

function renderTabs(){
  const all = allGroups();
  document.getElementById('tabs').innerHTML=all.map((g,i)=>
    `<button class="tab${i===cur?' active':''}" onclick="sw(${i})">${g.name}</button>`
  ).join('');
}

function getPrevSig(id) {
  try {
    // 優先用掃描前備份，其次用上次掃描結果
    const pre = JSON.parse(localStorage.getItem(SK+'_pre')||'{}');
    if (pre[id]) return pre[id];
    const d = JSON.parse(localStorage.getItem(SK)||'{}');
    return d[id] || null;
  } catch(e){ return null; }
}
function saveSigs() {
  // 掃描完成後儲存最新訊號
  const d = {};
  groups.forEach(g => {
    (g.stocks||[]).forEach(s => {
      if (s.daily) d[s.id] = s.daily.action;
    });
  });
  localStorage.setItem(SK, JSON.stringify(d));
}
function savePreScanSigs() {
  // 掃描前儲存目前訊號，只在有資料時才儲存
  const d = JSON.parse(localStorage.getItem(SK)||'{}');
  const hasData = groups.some(g => (g.stocks||[]).some(s => s.daily));
  if (hasData) {
    const pre = {};
    groups.forEach(g => {
      (g.stocks||[]).forEach(s => {
        if (s.daily) pre[s.id] = s.daily.action;
      });
    });
    localStorage.setItem(SK+'_pre', JSON.stringify(pre));
  }
}

function sigOrder(action) {
  return action==='買進'?0: action==='持有'?1: action==='賣出'?2: 3;
}
function sortBySignal(arr) {
  return arr.slice().sort((a,b) => {
    const da = a.daily ? sigOrder(a.daily.action) : 4;
    const db = b.daily ? sigOrder(b.daily.action) : 4;
    return da - db;
  });
}

function renderSpecial(type) {
  renderTabs();
  const title = type==='near' ? '均線買點' : type==='down' ? '回踩買點' : type==='change' ? '訊號異動' : '創新高';
  // 收集所有5個群組中符合條件的股票
  const seen = new Set();
  const matched = [];
  groups.forEach(g => {
    (g.stocks||[]).forEach(s => {
      if (!s.daily) return;
      if (seen.has(s.id)) return;
      if (type==='near') {
        const hasNear = s.near_ma5||s.near_ma10||s.near_ma20||s.near_ma60d||s.near_ma60;
        if (hasNear) { matched.push(s); seen.add(s.id); }
      } else if (type==='down') {
        const isDown = s.daily.action==='持有' && s.prev_price && s.price < s.prev_price;
        if (isDown) { matched.push(s); seen.add(s.id); }
      } else if (type==='change') {
        const prev = s.yesterday && s.yesterday.action;
        if (prev && prev !== s.daily.action) {
          matched.push({...s, prevAction: prev}); seen.add(s.id);
        }
      } else if (type==='newhigh') {
        if (s.new_high_10) { matched.push(s); seen.add(s.id); }
      }
    });
  });

  let h = `<div class="grp-bar"><div class="grp-name-inp">${title}</div></div>
  <div class="upd-time">掃描前5個群組後自動更新</div>`;

  if (matched.length === 0) {
    h += `<div class="empty">目前無符合條件的股票</div>`;
  } else {
    h += `<div class="tbl-hdr">
      <span class="col-id">代號</span>
      <span class="col-price">收盤價</span>
      <span class="col-sig">訊號／均線</span>
      <span class="col-del"></span>
    </div>`;
    const sortedMatched = sortBySignal(matched);
  if (type==='change') {
    h += sortedMatched.map((s,si) => {
      const card = rc(s, cur, si, true);
      const arrow = `<div style="font-size:12px;color:#ff9f0a;padding:2px 14px 6px">${s.prevAction} → ${s.daily.action}</div>`;
      return card + arrow;
    }).join('');
  } else {
    h += sortedMatched.map((s,si) => rc(s, cur, si, true)).join('');
  }
  }
  document.getElementById('main').innerHTML = h;
}

function render(){
  renderTabs();
  // 特殊群組
  if(cur === 5) { renderSpecial('near'); return; }
  if(cur === 6) { renderSpecial('down'); return; }
  if(cur === 7) { renderSpecial('change'); return; }
  if(cur === 8) { renderSpecial('newhigh'); return; }
  const g=groups[cur];
  let h=`
  <div class="grp-bar">
    <input class="grp-name-inp" value="${g.name}"
      onchange="rn(${cur},this.value)" onblur="rn(${cur},this.value)">
    <button class="scan-btn" id="scanBtn" onclick="scan(${cur})">⚡ 掃描</button>
  </div>
  <div class="upd-time" id="upd">${g.lastUpdate||'尚未掃描'}</div>
  <div class="add-row">
    <input class="add-inp" id="addInp" placeholder="輸入代號，如 2330、3624"
      onkeydown="if(event.key==='Enter')add(${cur})">
    <button class="add-btn" onclick="add(${cur})">＋</button>
  </div>`;

  if(!g.stocks||g.stocks.length===0){
    h+=`<div class="empty">尚無股票<br>輸入代號按 ＋ 新增</div>`;
  } else {
    h+=`<div class="tbl-hdr">
      <span class="col-id">代號</span>
      <span class="col-price">收盤價</span>
      <span class="col-sig">訊號／均線</span>
      <span class="col-del"></span>
    </div>`;
    h+=g.stocks.map((s,si)=>rc(s,cur,si)).join('');
  }
  document.getElementById('main').innerHTML=h;
}

function rc(s,gi,si,readonly=false){
  if(!s.daily){
    return `<div class="row row-pending">
      <span class="r-id">${s.id}</span>
      <span class="r-price">—</span>
      <div class="r-mid"><span style="color:#a0b4c8;font-size:13px">尚未查詢</span></div>
      ${readonly?'':`<button class="r-del" onclick="del(${gi},${si})">×</button>`}
    </div>`;
  }
  const d=s.daily, w=s.weekly||{action:'空手',days:0};
  const dt=d.days>0?`<span class="sig-days">${d.days}天</span>`:'';
  const wt=w.days>0?`<span class="sig-days">${w.days}週</span>`:'';
  const mv=(val,lbl,p,near)=>val
    ?`<div class="ma-item"><span class="ma-val ${maColor(p,val)}">${val}${near?' 😊':''}</span><span class="ma-lbl">${lbl}</span></div>`
    :`<div class="ma-item"><span class="ma-val ma-na">—</span><span class="ma-lbl">${lbl}</span></div>`;
  const isHoldingDown = s.daily && s.daily.action==='持有' && s.prev_price && s.price < s.prev_price;
  const rowStyle = isHoldingDown ? ' style="background:#c0145a;"' : '';
  return `<div class="row"${rowStyle}>
    <div class="r-id-wrap">
      <span class="r-id">${s.id}</span>
      ${s.name?`<span class="r-name">${s.name}</span>`:''}
    </div>
    <span class="r-price">${s.price}</span>
    <div class="r-mid">
      <div class="sig-line">
        <span class="sig-lbl">日</span>
        <span class="sig-txt ${sigColor(d.action)}">${d.action}</span>
        ${dt}
      </div>
      <div class="sig-line">
        <span class="sig-lbl">週</span>
        <span class="sig-txt ${sigColor(w.action)}">${w.action}</span>
        ${wt}
      </div>
      <div class="ma-row">
        ${mv(s.ma5,'MA5',s.price,s.near_ma5)}
        ${mv(s.ma10,'MA10',s.price,s.near_ma10)}
        ${mv(s.ma20,'MA20',s.price,s.near_ma20)}
      </div>
      <div class="ma-row">
        ${mv(s.ma60d,'MA60',s.price,s.near_ma60d)}
        ${mv(s.ma60k240,'60MA240',s.price,s.near_ma60)}
      </div>
    </div>
    <button class="r-del" onclick="del(${gi},${si})">×</button>
  </div>`;
}

function sw(i){ cur=i; render(); }
function rn(gi,v){ groups[gi].name=v.trim()||DN[gi]; sgr(); renderTabs(); }

function add(gi){
  const inp=document.getElementById('addInp');
  const id=inp.value.trim().toUpperCase();
  if(!id) return;
  if(groups[gi].stocks.find(s=>s.id===id)){alert('已有此代號');return;}
  groups[gi].stocks.push({id}); sgr(); inp.value=''; render();
}

function del(gi,si){ groups[gi].stocks.splice(si,1); sgr(); render(); }

async function scan(gi){
  const stocks=groups[gi].stocks;
  if(!stocks||stocks.length===0){alert('請先新增股票');return;}
  // 掃描前先備份當前訊號
  savePreScanSigs();
  const btn=document.getElementById('scanBtn');
  btn.disabled=true; btn.textContent='查詢中…';

  // 顯示 loading
  const tbl=document.getElementById('main');
  const ids=stocks.map(s=>s.id).join(',');
  try{
    const res=await fetch('/api/batch?ids='+encodeURIComponent(ids));
    const data=await res.json();
    const hs=[];
    stocks.forEach(s=>{
      const r=data[s.id];
      if(r){
        s.price=r.price; s.prev_price=r.prev_price;
        s.ma5=r.ma5; s.ma10=r.ma10; s.ma20=r.ma20; s.ma60d=r.ma60d; s.ma60k240=r.ma60k240;
        s.near_ma5=r.near_ma5; s.near_ma10=r.near_ma10;
        s.near_ma20=r.near_ma20; s.near_ma60d=r.near_ma60d; s.near_ma60=r.near_ma60;
        s.daily=r.daily; s.weekly=r.weekly; s.yesterday=r.yesterday; s.new_high_10=r.new_high_10;
        s.name=r.name||'';
        hs.push({id:s.id,price:r.price,daily:r.daily,weekly:r.weekly});
      }
    });
    if(hs.length>0){
      const hist=lhi(), today=dk();
      let de=hist.find(h=>h.date===today);
      if(!de){de={date:today,scans:[]};hist.unshift(de);}
      de.scans.unshift({time:ts(),group:groups[gi].name,stocks:hs});
      if(hist.length>30) hist.splice(30);
      shi(hist);
    }
    groups[gi].stocks = sortBySignal(groups[gi].stocks);
    groups[gi].lastUpdate='更新：'+ts(); sgr(); saveSigs();
  }catch(e){alert('連線失敗，請稍後再試');}
  btn.disabled=false; btn.textContent='⚡ 掃描';
  render();
}

async function autoScan(){
  for(let i=0;i<groups.length;i++){
    if(groups[i].stocks&&groups[i].stocks.length>0){
      cur=i; render(); await scan(i);
    }
  }
  // 掃描完後，如果在特殊群組頁則重新渲染
  if(cur<5) {
    cur=groups.findIndex(g=>g.stocks&&g.stocks.length>0);
    if(cur<0) cur=0;
  }
  render();
}

async function saveCloud(){
  const btn=document.getElementById('btnSave');
  btn.textContent='儲存中…'; btn.disabled=true;
  const rows=[];
  groups.forEach((g,gi)=>{
    if(g.stocks&&g.stocks.length>0) g.stocks.forEach(s=>rows.push([gi,g.name,s.id]));
    else rows.push([gi,g.name,'']);
  });
  try{
    const res=await fetch('/api/sync-save',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({payload:rows})
    });
    const j=await res.json();
    btn.textContent=j.ok?'✓ 已儲存':'✗ 失敗';
  }catch(e){btn.textContent='✗ 失敗';}
  setTimeout(()=>{btn.textContent='↑ 存雲端';btn.disabled=false;},2000);
}

async function loadCloud(){
  const btn=document.getElementById('btnLoad');
  btn.textContent='載入中…'; btn.disabled=true;
  try{
    const res=await fetch('/api/sync-load',{signal:AbortSignal.timeout(20000)});
    const j=await res.json();
    const rows=j.data||[];
    if(rows.length===0){alert('雲端無資料');btn.textContent='⬇ 載雲端';btn.disabled=false;return;}
    const ng=DN.map((n,i)=>({name:n,stocks:[]}));
    // 先更新所有群組名稱（包含空群組）
    rows.forEach(row=>{
      const gi=parseInt(row[0]);
      if(gi>=0&&gi<5 && row[1]) ng[gi].name=row[1];
    });
    // 再加入有股票的列
    rows.filter(r=>r&&String(r[2]||'').trim()!=='').forEach(row=>{
      const gi=parseInt(row[0]), sid=String(row[2]||'').trim().toUpperCase();
      if(gi>=0&&gi<5 && sid && !ng[gi].stocks.find(s=>s.id===sid)) ng[gi].stocks.push({id:sid});
    });
    groups=ng; sgr(); 
    // 強制清掉舊版 key，避免下次讀到過期資料
    localStorage.removeItem('ga_g_v4');
    render();
    btn.textContent='✓ 已載入';
    setTimeout(()=>{btn.textContent='⬇ 載雲端';btn.disabled=false;},1500);
    autoScan();
  }catch(e){
    btn.textContent='✗ '+(e.message||'失敗'); btn.disabled=false;
    setTimeout(()=>{btn.textContent='⬇ 載雲端';btn.disabled=false;},3000);
  }
}

function toggleHist(){
  const o=document.getElementById('histOverlay');
  o.classList.toggle('open');
  if(o.classList.contains('open')) renderHist();
}
function closeHistBg(e){if(e.target===document.getElementById('histOverlay'))toggleHist();}

function renderHist(){
  const hist=lhi(), el=document.getElementById('histList');
  if(!hist||hist.length===0){el.innerHTML='<div class="hist-none">尚無歷史紀錄</div>';return;}
  let h='';
  hist.forEach(day=>{
    h+=`<div class="h-date">📅 ${day.date}</div>`;
    day.scans.forEach(sc=>{
      h+=`<div class="h-meta">${sc.time} · ${sc.group}</div>`;
      sc.stocks.forEach(s=>{
        const d=s.daily||{}, w=s.weekly||{};
        h+=`<div class="h-row">
          <span class="h-id">${s.id}</span>
          <span class="h-price">${s.price}</span>
          <span class="${sigColor(d.action)}" style="font-size:13px">${d.signal} 日${d.action||''}</span>
          <span class="${sigColor(w.action)}" style="font-size:13px">${w.signal} 週${w.action||''}</span>
        </div>`;
      });
    });
  });
  el.innerHTML=h;
}

function clearHist(){if(!confirm('確定清除所有歷史？'))return;shi([]);renderHist();}

render();
window.addEventListener('load',()=>{ setTimeout(()=>loadCloud(),1500); });
</script>
</body>
</html>"""


@app.route('/')
def home():
    return HTML_PAGE

if __name__ == '__main__':
    app.run()
