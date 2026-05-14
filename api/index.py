from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

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

    # 前天是否觸發賣出（yest_sell = 昨天已是賣出狀態，今天收盤後才空手）
    day2_sell = False
    day2_buy  = False
    yest_sell = False
    yest_buy  = False
    if len(close_series) >= 4:
        yest_price     = float(close_series.iloc[-2])
        yest_prev_low  = float(close_series.iloc[-4:-2].min())
        yest_prev_high = float(close_series.iloc[-4:-2].max())
        yest_sell      = (yest_price < yest_prev_low)
        yest_buy       = (yest_price > yest_prev_high)
    if len(close_series) >= 5:
        day2_price     = float(close_series.iloc[-3])
        day2_prev_low  = float(close_series.iloc[-5:-3].min())
        day2_prev_high = float(close_series.iloc[-5:-3].max())
        day2_sell      = (day2_price < day2_prev_low)
        day2_buy       = (day2_price > day2_prev_high)

    if status == 'holding':
        if price < prev2_low:
            # 今天跌破 → 賣出
            signal, action = '', '賣出'
        elif yest_sell:
            # 昨天跌破 → 還是賣出（今天開盤賣，收盤後才空手）
            signal, action = '', '賣出'
        elif day2_sell:
            # 前天跌破，昨天已執行賣出 → 今天空手
            signal, action = '', '空手'
        elif buy_day == len(close_series) - 1:
            # 今天突破 → 買進
            signal, action = '', '買進'
        elif yest_buy:
            # 昨天突破買進 → 今天持有
            signal, action = '', '持有'
        else:
            signal, action = '', '持有'
        hold_days = (len(close_series) - 1) - buy_day if buy_day is not None else 0
    else:
        if price > prev2_high:
            # 今天突破 → 買進
            signal, action = '', '買進'
        elif yest_buy:
            # 昨天突破，今天開盤買 → 今天收盤持有（由holding狀態處理）
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
        price = round(float(close_d.iloc[-1]), 2)
        ma5   = round(float(close_d.iloc[-5:].mean()),  2) if len(close_d) >= 5  else None
        ma10  = round(float(close_d.iloc[-10:].mean()), 2) if len(close_d) >= 10 else None
        d_signal, d_action, d_days = calc_signal(close_d.iloc[-20:])

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
  color: #e2e8f0;
  font-family: -apple-system, 'SF Pro Text', sans-serif;
  min-height: 100vh;
  font-size: 15px;
}

/* ── header ── */
.hdr {
  position: sticky; top: 0; z-index: 100;
  background: #0d1b2a;
  border-bottom: 1px solid #1e3a5f;
  padding: 10px 14px 0;
}
.hdr-top {
  display: flex; align-items: center;
  justify-content: space-between; margin-bottom: 10px;
}
.logo { font-size: 16px; font-weight: 800; color: #38bdf8; letter-spacing: 1px; }
.hdr-btns { display: flex; gap: 6px; }
.hbtn {
  font-size: 12px; padding: 5px 11px;
  border: 1px solid #1e3a5f; border-radius: 20px;
  background: transparent; color: #4a6fa5; cursor: pointer;
}
.hbtn:active { background: #132338; }
.hbtn:disabled { opacity: .4; }

/* tabs */
.tabs {
  display: flex; gap: 4px;
  overflow-x: auto; scrollbar-width: none;
  padding-bottom: 0;
}
.tabs::-webkit-scrollbar { display: none; }
.tab {
  flex-shrink: 0;
  padding: 7px 14px 8px;
  font-size: 13px; font-weight: 500;
  color: #4a6fa5; cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap; background: none; border-top: none; border-left: none; border-right: none;
}
.tab.active { color: #38bdf8; border-bottom-color: #38bdf8; font-weight: 700; }

/* ── main ── */
.main { padding: 12px 0 80px; max-width: 540px; margin: 0 auto; }

/* group top bar */
.grp-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 0 14px; margin-bottom: 4px;
}
.grp-name-inp {
  flex: 1; background: transparent; border: none;
  color: #e2e8f0; font-size: 15px; font-weight: 700;
  padding: 4px 0; font-family: inherit;
  border-bottom: 1px dashed #1e3a5f;
}
.grp-name-inp:focus { outline: none; border-bottom-color: #38bdf8; }
.scan-btn {
  padding: 6px 16px; background: #38bdf8; color: #000;
  border: none; border-radius: 20px; font-size: 13px; font-weight: 700; cursor: pointer;
}
.scan-btn:disabled { background: #1e3a5f; color: #4a6fa5; cursor: default; }
.upd-time { font-size: 11px; color: #4a6fa5; padding: 0 14px 8px; font-variant-numeric: tabular-nums; }

/* add row */
.add-row { display: flex; gap: 8px; padding: 0 14px 10px; }
.add-inp {
  flex: 1; background: #132338; border: 1px solid #1e3a5f;
  border-radius: 10px; padding: 9px 12px;
  color: #e2e8f0; font-size: 14px;
}
.add-inp::placeholder { color: #2d5480; }
.add-inp:focus { outline: none; border-color: #38bdf8; }
.add-btn {
  width: 42px; background: #132338; border: 1px solid #1e3a5f;
  border-radius: 10px; color: #38bdf8; font-size: 22px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}

/* ── 表頭 ── */
.tbl-hdr {
  display: flex; align-items: center;
  padding: 4px 14px;
  border-bottom: 1px solid #1e3a5f;
  margin-bottom: 2px;
}
.tbl-hdr span { font-size: 11px; color: #7aa8d0; }
.col-id    { width: 52px; }
.col-price { width: 56px; text-align: right; }
.col-sig   { flex: 1; padding-left: 10px; }
.col-mas   { width: 150px; display: flex; justify-content: flex-end; gap: 0; }
.col-del   { width: 24px; }

/* ── 股票列 ── */
.row {
  display: flex; align-items: center;
  padding: 11px 14px;
  border-bottom: 1px solid #132338;
}
.row:active { background: #132338; }

.r-id {
  width: 52px;
  font-size: 16px; font-weight: 700; color: #38bdf8;
  font-variant-numeric: tabular-nums;
}
.r-price {
  width: 56px; text-align: right;
  font-size: 16px; font-weight: 600; color: #e2e8f0;
  font-variant-numeric: tabular-nums;
}
.r-mid {
  flex: 1; padding-left: 10px;
  display: flex; flex-direction: column; gap: 4px;
}
.sig-line {
  display: flex; align-items: baseline; gap: 5px;
}
.sig-lbl  { font-size: 12px; color: #7aa8d0; width: 16px; flex-shrink: 0; font-weight: 600; }
.sig-txt  { font-size: 15px; font-weight: 700; }
.sig-days { font-size: 11px; color: #ff9f0a; font-weight: 600; }
.ma-row {
  display: flex; gap: 10px;
}
.ma-item { display: flex; flex-direction: column; align-items: flex-start; }
.ma-val  { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.ma-lbl  { font-size: 10px; color: #7aa8d0; }
.c-buy  { color: #34c759; }
.c-hold { color: #ffd60a; }
.c-sell { color: #ff453a; }
.c-idle { color: #94a3b8; }
.ma-up  { color: #34c759; }
.ma-dn  { color: #ff453a; }
.ma-na  { color: #2d5480; }

.r-del {
  width: 24px; text-align: right;
  background: none; border: none;
  color: #2d5480; font-size: 16px; cursor: pointer; padding: 2px;
  align-self: flex-start; margin-top: 2px;
}
.r-del:active { color: #ff453a; }
.row-pending .r-price { color: #2d5480; }

/* empty */
.empty {
  padding: 40px 14px; text-align: center;
  color: #2d5480; font-size: 14px; line-height: 2.2;
}

/* loading */
.loading {
  padding: 20px 14px; text-align: center;
  color: #4a6fa5; font-size: 13px;
}

/* ── history panel ── */
.hist-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,.6);
  display: none; align-items: flex-end;
}
.hist-overlay.open { display: flex; }
.hist-sheet {
  width: 100%; max-width: 540px; margin: 0 auto;
  background: #132338;
  border-radius: 18px 18px 0 0;
  border-top: 1px solid #1e3a5f;
  max-height: 70vh; display: flex; flex-direction: column;
}
.hist-top {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid #1e3a5f;
}
.hist-title { font-size: 15px; font-weight: 700; }
.hist-x { background: none; border: none; color: #4a6fa5; font-size: 22px; cursor: pointer; }
.hist-list { overflow-y: auto; flex: 1; }
.h-date { font-size: 11px; color: #38bdf8; padding: 10px 16px 4px; }
.h-meta { font-size: 11px; color: #2d5480; padding: 0 16px 4px; }
.h-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 16px; border-bottom: 1px solid #0d1b2a;
  font-size: 13px;
}
.h-id    { color: #38bdf8; width: 46px; font-weight: 600; }
.h-price { color: #e2e8f0; width: 50px; text-align: right; font-variant-numeric: tabular-nums; }
.hist-none { padding: 24px; text-align: center; color: #2d5480; font-size: 13px; }
.hist-clr {
  margin: 8px 14px; padding: 9px;
  border: 1px solid #1e3a5f; border-radius: 10px;
  background: none; color: #4a6fa5; font-size: 12px; cursor: pointer;
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
const GK = 'ga_g_v5', HK = 'ga_h_v5';
const DN = ['短線強勢股','波段持股','觀察名單','自選群組4','自選群組5'];

function lgr() {
  try { const d=JSON.parse(localStorage.getItem(GK)); if(d&&d.length===5) return d; } catch(e){}
  return DN.map(n=>({name:n,stocks:[]}));
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
  document.getElementById('tabs').innerHTML=groups.map((g,i)=>
    `<button class="tab${i===cur?' active':''}" onclick="sw(${i})">${g.name}</button>`
  ).join('');
}

function render(){
  renderTabs();
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

function rc(s,gi,si){
  if(!s.daily){
    return `<div class="row row-pending">
      <span class="r-id">${s.id}</span>
      <span class="r-price">—</span>
      <div class="r-mid"><span style="color:#2d5480;font-size:13px">尚未查詢</span></div>
      <button class="r-del" onclick="del(${gi},${si})">×</button>
    </div>`;
  }
  const d=s.daily, w=s.weekly||{action:'空手',days:0};
  const dt=d.days>0?`<span class="sig-days">${d.days}天</span>`:'';
  const wt=w.days>0?`<span class="sig-days">${w.days}週</span>`:'';
  const mv=(val,lbl,p)=>val
    ?`<div class="ma-item"><span class="ma-val ${maColor(p,val)}">${val}</span><span class="ma-lbl">${lbl}</span></div>`
    :`<div class="ma-item"><span class="ma-val ma-na">—</span><span class="ma-lbl">${lbl}</span></div>`;
  return `<div class="row">
    <span class="r-id">${s.id}</span>
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
        ${mv(s.ma60k240,'60MA240',s.price)}
        ${mv(s.ma5,'MA5',s.price)}
        ${mv(s.ma10,'MA10',s.price)}
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
        s.price=r.price; s.ma5=r.ma5; s.ma10=r.ma10;
        s.ma60k240=r.ma60k240; s.daily=r.daily; s.weekly=r.weekly;
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
    groups[gi].lastUpdate='更新：'+ts(); sgr();
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
  cur=groups.findIndex(g=>g.stocks&&g.stocks.length>0);
  if(cur<0) cur=0; render();
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
