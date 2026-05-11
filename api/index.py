from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

GAS_URL = "https://script.google.com/macros/s/AKfycbyD6DnxV3p7j7M2PZzGarqSOBobpADkAsbVV497-YXD-FkWiyfRr55kFie2yw0B4_U8Ow/exec"

def fetch_df(stock_id):
    """自動判斷上市/上櫃，回傳 DataFrame"""
    if stock_id.endswith(".TW") or stock_id.endswith(".TWO"):
        tickers = [stock_id]
    else:
        tickers = [stock_id + ".TW", stock_id + ".TWO"]
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="60d", auto_adjust=True, progress=False)
            if not df.empty and len(df) >= 20:
                return df
        except:
            continue
    return None

def get_signal_20d(stock_id):
    try:
        df = fetch_df(stock_id)
        if df is None:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            close = df['Close'].iloc[:, 0].dropna()
            high  = df['High'].iloc[:, 0].dropna()
            low   = df['Low'].iloc[:, 0].dropna()
            vol   = df['Volume'].iloc[:, 0].dropna()
        else:
            close = df['Close'].dropna()
            high  = df['High'].dropna()
            low   = df['Low'].dropna()
            vol   = df['Volume'].dropna()

        c20 = close.iloc[-20:]
        status  = 'watching'
        buy_day = None
        for i in range(2, len(c20)):
            price      = float(c20.iloc[i])
            prev2_high = float(c20.iloc[i-2:i].max())
            prev2_low  = float(c20.iloc[i-2:i].min())
            if status == 'watching':
                if price > prev2_high:
                    status  = 'holding'
                    buy_day = i
            else:
                if price < prev2_low:
                    status  = 'watching'
                    buy_day = None

        price      = float(c20.iloc[-1])
        prev2_high = float(c20.iloc[-3:-1].max())
        prev2_low  = float(c20.iloc[-3:-1].min())

        if status == 'holding':
            if price < prev2_low:
                signal, action = '🔴', '賣出'
            elif buy_day == len(c20) - 1:
                signal, action = '🟢', '買進'
            else:
                signal, action = '🟡', '持有'
            hold_days = (len(c20) - 1) - buy_day if buy_day is not None else 0
        else:
            if price > prev2_high:
                signal, action = '🟢', '買進'
            else:
                signal, action = '⬜', '空手'
            hold_days = 0

        # 關鍵壓力支撐
        h5       = float(high.iloc[-5:].max())
        h10      = float(high.iloc[-10:].max())
        l5       = float(low.iloc[-5:].min())
        ma5      = float(close.iloc[-5:].mean())
        vol_idx  = int(vol.iloc[-20:].values.argmax())
        vk_high  = float(high.iloc[-20:].iloc[vol_idx])
        vk_low   = float(low.iloc[-20:].iloc[vol_idx])

        r_cands = [v for v in [h5, h10, vk_high] if v > price]
        s_cands = [v for v in [l5, ma5, vk_low] if v < price]

        resistance = round(min(r_cands), 2) if r_cands else None
        support    = round(max(s_cands), 2) if s_cands else None

        return {
            'signal':     signal,
            'action':     action,
            'price':      round(price, 2),
            'hold_days':  hold_days,
            'resistance': resistance,
            'support':    support,
        }
    except:
        return None

@app.route('/api/check', methods=['GET'])
def check_stock():
    stock_id = request.args.get('id', '').strip().upper()
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
    stock_list = [s.strip().upper() for s in ids.split(',') if s.strip()]
    results = {}
    for stock_id in stock_list:
        results[stock_id] = get_signal_20d(stock_id)
    return jsonify(results)

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>GA 買賣訊號</title>
<style>
:root {
  --bg:      #1a1a1a;
  --bg2:     #222;
  --bg3:     #2a2a2a;
  --bg4:     #2e2e2e;
  --border:  rgba(255,255,255,0.09);
  --text1:   #f0f0f0;
  --text2:   #999;
  --text3:   #555;
  --accent:  #0a84ff;
  --green:   #30d158;
  --yellow:  #ffd60a;
  --red:     #ff453a;
  --grey:    #636366;
  --radius:  14px;
  --radius-s:10px;
}
* { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }
body { font-family:-apple-system,"Helvetica Neue",sans-serif; background:var(--bg); color:var(--text1); min-height:100vh; padding-bottom:40px; }
.header { padding:52px 20px 0; margin-bottom:20px; }
.header h1 { font-size:1.8rem; font-weight:700; letter-spacing:-0.04em; }
.header p  { font-size:0.78rem; color:var(--text3); margin-top:3px; }
.sync-bar { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:0 16px 14px; flex-wrap:wrap; }
.btn-sync { padding:6px 13px; border-radius:20px; border:1px solid var(--border); background:var(--bg3); color:var(--text2); font-size:0.75rem; font-weight:500; cursor:pointer; font-family:inherit; transition:all .2s; }
.btn-sync:active { background:var(--bg4); color:var(--text1); }
.sync-st { font-size:0.7rem; color:var(--text3); }
.tabs-wrap { padding:0 16px; margin-bottom:14px; overflow-x:auto; scrollbar-width:none; }
.tabs-wrap::-webkit-scrollbar { display:none; }
.tabs { display:flex; gap:8px; width:max-content; }
.tab { padding:6px 15px; border-radius:20px; font-size:0.82rem; font-weight:500; cursor:pointer; border:1px solid var(--border); color:var(--text2); background:var(--bg4); transition:all .2s; white-space:nowrap; }
.tab.active { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.panel { display:none; padding:0 16px; }
.panel.active { display:block; }
.card { background:var(--bg4); border-radius:var(--radius); border:1px solid var(--border); overflow:hidden; }
.gname-wrap { padding:16px 16px 12px; }
.gname { width:100%; background:transparent; border:none; font-size:1.05rem; font-weight:600; color:var(--text1); font-family:inherit; letter-spacing:-0.02em; }
.gname:focus { outline:none; }
.sep { height:1px; background:var(--border); }
.add-row { display:flex; gap:8px; padding:12px 16px; }
.add-inp { flex:1; background:var(--bg3); border:1px solid var(--border); border-radius:var(--radius-s); padding:9px 13px; color:var(--text1); font-size:0.88rem; font-family:inherit; transition:border-color .2s; }
.add-inp:focus { outline:none; border-color:var(--accent); }
.add-inp::placeholder { color:var(--text3); }
.btn-add { padding:9px 16px; border-radius:var(--radius-s); border:none; background:var(--accent); color:#fff; font-size:0.85rem; font-weight:600; cursor:pointer; font-family:inherit; transition:opacity .2s; }
.btn-add:active { opacity:.7; }
.tbl-head { display:grid; grid-template-columns:52px 56px 76px 44px 60px 60px 28px; gap:4px; padding:8px 16px; border-top:1px solid var(--border); }
.tbl-head span { font-size:0.6rem; color:var(--text3); font-weight:600; letter-spacing:0.05em; text-transform:uppercase; }
.tbl-head span:nth-child(2),
.tbl-head span:nth-child(4),
.tbl-head span:nth-child(5),
.tbl-head span:nth-child(6) { text-align:right; }
.srow { display:grid; grid-template-columns:52px 56px 76px 44px 60px 60px 28px; gap:4px; align-items:center; padding:11px 16px; border-top:1px solid var(--border); }
.srow:active { background:rgba(255,255,255,0.03); }
.c-id    { font-size:0.85rem; font-weight:600; color:var(--text1); }
.c-price { font-size:0.85rem; font-weight:500; color:var(--text1); text-align:right; }
.c-sig   { font-size:0.78rem; font-weight:600; display:flex; align-items:center; gap:3px; }
.c-days  { font-size:0.75rem; color:var(--text2); text-align:right; }
.c-lv    { font-size:0.8rem; text-align:right; }
.c-lv.resist { color:#ff6b6b; }
.c-lv.supprt { color:#5ec75e; }
.c-lv.new-high { color:#ff9f0a; font-size:0.7rem; }
.c-lv.new-low  { color:#64d2ff; font-size:0.7rem; }
.c-del { display:flex; justify-content:flex-end; }
.btn-del { width:22px; height:22px; border-radius:50%; border:none; background:rgba(255,69,58,.12); color:var(--red); font-size:0.9rem; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.btn-del:active { background:rgba(255,69,58,.35); }
.sig-g { color:var(--green); }
.sig-y { color:var(--yellow); }
.sig-r { color:var(--red); }
.sig-w { color:var(--grey); }
.empty   { padding:28px 16px; text-align:center; color:var(--text3); font-size:0.82rem; border-top:1px solid var(--border); }
.loading { padding:20px 16px; text-align:center; color:var(--text3); font-size:0.82rem; border-top:1px solid var(--border); }
.err     { padding:12px 16px; color:var(--red); font-size:0.8rem; border-top:1px solid var(--border); }
.bot { display:flex; align-items:center; justify-content:space-between; padding:12px 16px; border-top:1px solid var(--border); }
.upd { font-size:0.7rem; color:var(--text3); }
.btn-scan { padding:8px 18px; border-radius:20px; border:none; background:var(--green); color:#000; font-size:0.82rem; font-weight:700; cursor:pointer; font-family:inherit; display:flex; align-items:center; gap:5px; transition:opacity .2s; }
.btn-scan:active { opacity:.7; }
.btn-scan:disabled { background:var(--bg3); color:var(--text3); cursor:not-allowed; }
</style>
</head>
<body>
<div class="header">
  <h1>&#9989; GA 買賣訊號</h1>
  <p>2 日高低點突破系統</p>
</div>
<div class="sync-bar">
  <span class="sync-st" id="syncSt">尚未同步</span>
  <button class="btn-sync" onclick="syncDown()">&#9729; 從雲端載入</button>
  <button class="btn-sync" onclick="syncUp()">&#8593; 儲存至雲端</button>
</div>
<div class="tabs-wrap"><div class="tabs" id="tabs"></div></div>
<div id="panels"></div>

<script>
var GAS="https://script.google.com/macros/s/AKfycbyD6DnxV3p7j7M2PZzGarqSOBobpADkAsbVV497-YXD-FkWiyfRr55kFie2yw0B4_U8Ow/exec";
var DEF=[
  {name:"短線強勢股",stocks:[]},{name:"波段持股",stocks:[]},
  {name:"觀察名單",stocks:[]},{name:"自選群組4",stocks:[]},{name:"自選群組5",stocks:[]}
];
function loadL(){ try{ var s=localStorage.getItem("ga_v3"); return s?JSON.parse(s):DEF; }catch(e){ return DEF; } }
function saveL(){ localStorage.setItem("ga_v3",JSON.stringify(groups)); }
var groups=loadL(), activeTab=0;

function g2rows(gs){
  var rows=[];
  gs.forEach(function(g,gi){
    if(g.stocks&&g.stocks.length>0){ g.stocks.forEach(function(s){ rows.push([gi,g.name,s.id]); }); }
    else{ rows.push([gi,g.name,'']); }
  });
  return rows;
}
function rows2g(rows){
  var gs=DEF.map(function(g){ return {name:g.name,stocks:[]}; });
  rows.forEach(function(r){
    if(!r||r.length<3) return;
    var gi=parseInt(r[0]);
    if(isNaN(gi)||gi<0||gi>4) return;
    gs[gi].name=r[1]||gs[gi].name;
    if(r[2]) gs[gi].stocks.push({id:String(r[2])});
  });
  return gs;
}
function setSt(m){ document.getElementById("syncSt").textContent=m; }
function syncUp(){
  setSt("儲存中...");
  fetch(GAS+"?action=save&payload="+encodeURIComponent(JSON.stringify(g2rows(groups))))
    .then(function(r){return r.json();})
    .then(function(d){ setSt(d.ok?"已儲存 "+new Date().toLocaleTimeString():"儲存失敗"); })
    .catch(function(){ setSt("儲存失敗"); });
}
function syncDown(){
  setSt("載入中...");
  fetch(GAS+"?action=load")
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.data&&d.data.length>0){
        groups=rows2g(d.data); saveL(); activeTab=0; render();
        setSt("已載入 "+new Date().toLocaleTimeString());
      } else { setSt("雲端無資料"); }
    })
    .catch(function(){ setSt("載入失敗"); });
}

function render(){
  var te=document.getElementById("tabs"),pe=document.getElementById("panels");
  te.innerHTML=""; pe.innerHTML="";
  groups.forEach(function(g,i){
    var t=document.createElement("div");
    t.className="tab"+(i===activeTab?" active":"");
    t.textContent=g.name||("群組"+(i+1));
    t.onclick=(function(idx){return function(){activeTab=idx;render();};})(i);
    te.appendChild(t);
    var p=document.createElement("div");
    p.className="panel"+(i===activeTab?" active":"");
    p.innerHTML=
      "<div class=\\"card\\">"+
      "<div class=\\"gname-wrap\\"><input class=\\"gname\\" value=\\""+esc(g.name)+"\\" placeholder=\\"群組名稱\\" onchange=\\"ren("+i+",this.value)\\"></div>"+
      "<div class=\\"sep\\"></div>"+
      "<div class=\\"add-row\\">"+
        "<input class=\\"add-inp\\" type=\\"text\\" id=\\"ai"+i+"\\" placeholder=\\"輸入代號，如 2330、6016\\" maxlength=\\"12\\" onkeydown=\\"if(event.key===&quot;Enter&quot;)addS("+i+")\\">"+
        "<button class=\\"btn-add\\" onclick=\\"addS("+i+")\\">新增</button>"+
      "</div>"+
      "<div class=\\"tbl-head\\">"+
        "<span>代號</span>"+
        "<span style=\\"text-align:right\\">收盤價</span>"+
        "<span>買賣訊號</span>"+
        "<span style=\\"text-align:right\\">天數</span>"+
        "<span style=\\"text-align:right\\">關鍵壓力</span>"+
        "<span style=\\"text-align:right\\">關鍵支撐</span>"+
        "<span></span>"+
      "</div>"+
      "<div class=\\"stock-list\\" id=\\"sl"+i+"\\">"+renderRows(g.stocks,i)+"</div>"+
      "<div class=\\"bot\\">"+
        "<span class=\\"upd\\" id=\\"ut"+i+"\\"></span>"+
        "<button class=\\"btn-scan\\" id=\\"sb"+i+"\\" onclick=\\"scan("+i+")\\">&#128269; 掃描訊號</button>"+
      "</div>"+
      "</div>";
    pe.appendChild(p);
  });
}

function renderRows(stocks,gi){
  if(!stocks||stocks.length===0) return "<div class=\\"empty\\">尚未新增股票</div>";
  return stocks.map(function(s,si){
    var sig=s.signal||"⬜", act=s.action||"—";
    var price=s.price!=null?s.price:"—";
    var days=s.hold_days>0?s.hold_days+"天":"—";
    var resCls="c-lv resist", supCls="c-lv supprt";
    var res,sup;
    if(s.resistance!=null){ res=s.resistance; }
    else { res="新高"; resCls="c-lv new-high"; }
    if(s.support!=null){ sup=s.support; }
    else { sup="新低"; supCls="c-lv new-low"; }
    var cls=sig==="🟢"?"sig-g":sig==="🟡"?"sig-y":sig==="🔴"?"sig-r":"sig-w";
    return "<div class=\\"srow\\">"+
      "<span class=\\"c-id\\">"+esc(s.id)+"</span>"+
      "<span class=\\"c-price\\">"+price+"</span>"+
      "<span class=\\"c-sig "+cls+"\\">"+sig+" "+act+"</span>"+
      "<span class=\\"c-days\\">"+days+"</span>"+
      "<span class=\\""+resCls+"\\">"+res+"</span>"+
      "<span class=\\""+supCls+"\\">"+sup+"</span>"+
      "<span class=\\"c-del\\"><button class=\\"btn-del\\" onclick=\\"delS("+gi+","+si+")\\">&#xd7;</button></span>"+
      "</div>";
  }).join("");
}

function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function ren(i,v){ groups[i].name=v; saveL(); document.querySelectorAll(".tab")[i].textContent=v||("群組"+(i+1)); }
function addS(i){
  var inp=document.getElementById("ai"+i), val=inp.value.trim().toUpperCase();
  if(!val) return;
  if(groups[i].stocks.find(function(s){return s.id===val;})){ alert("已存在此代號"); return; }
  groups[i].stocks.push({id:val}); saveL(); inp.value="";
  document.getElementById("sl"+i).innerHTML=renderRows(groups[i].stocks,i);
}
function delS(gi,si){ groups[gi].stocks.splice(si,1); saveL(); document.getElementById("sl"+gi).innerHTML=renderRows(groups[gi].stocks,gi); }
function scan(i){
  var stocks=groups[i].stocks;
  if(!stocks||stocks.length===0){ alert("請先新增股票"); return; }
  var ids=stocks.map(function(s){return s.id;}).join(",");
  var btn=document.getElementById("sb"+i);
  btn.disabled=true; btn.textContent="查詢中...";
  document.getElementById("sl"+i).innerHTML="<div class=\\"loading\\">&#9203; 查詢中，請稍候...</div>";
  fetch("/api/batch?ids="+encodeURIComponent(ids))
    .then(function(r){return r.json();})
    .then(function(data){
      stocks.forEach(function(s){
        var r=data[s.id];
        if(r){ s.signal=r.signal; s.action=r.action; s.price=r.price; s.hold_days=r.hold_days; s.resistance=r.resistance; s.support=r.support; }
      });
      saveL();
      document.getElementById("sl"+i).innerHTML=renderRows(stocks,i);
      var now=new Date();
      document.getElementById("ut"+i).textContent="更新 "+now.getFullYear()+"/"+(now.getMonth()+1)+"/"+now.getDate()+" "+now.getHours()+":"+String(now.getMinutes()).padStart(2,"0");
      btn.disabled=false; btn.innerHTML="&#128269; 掃描訊號";
    })
    .catch(function(){
      document.getElementById("sl"+i).innerHTML="<div class=\\"err\\">&#10060; 連線失敗，請稍後再試</div>";
      btn.disabled=false; btn.innerHTML="&#128269; 掃描訊號";
    });
}
render();
</script>
</body>
</html>"""

@app.route('/')
def home():
    return HTML_PAGE

if __name__ == '__main__':
    app.run()
