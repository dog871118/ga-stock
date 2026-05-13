from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

GAS_URL = "https://script.google.com/macros/s/AKfycbyD6DnxV3p7j7M2PZzGarqSOBobpADkAsbVV497-YXD-FkWiyfRr55kFie2yw0B4_U8Ow/exec"

def fetch_df(stock_id, period="60d", interval="1d"):
    if stock_id.endswith(".TW") or stock_id.endswith(".TWO"):
        tickers = [stock_id]
    else:
        tickers = [stock_id + ".TW", stock_id + ".TWO"]
    for ticker in tickers:
        try:
            df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
            if not df.empty and len(df) >= 5:
                return df
        except:
            continue
    return None

def get_signal_20d(stock_id):
    try:
        df = fetch_df(stock_id, period="60d", interval="1d")
        if df is None:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            close = df['Close'].iloc[:, 0].dropna()
        else:
            close = df['Close'].dropna()

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

        ma5  = round(float(close.iloc[-5:].mean()), 1)  if len(close) >= 5  else None
        ma10 = round(float(close.iloc[-10:].mean()), 1) if len(close) >= 10 else None

        ma60_240 = None
        try:
            df60 = fetch_df(stock_id, period="60d", interval="60m")
            if df60 is not None and len(df60) >= 10:
                if isinstance(df60.columns, pd.MultiIndex):
                    c60 = df60['Close'].iloc[:, 0].dropna()
                else:
                    c60 = df60['Close'].dropna()
                if len(c60) >= 240:
                    ma60_240 = round(float(c60.iloc[-240:].mean()), 1)
                else:
                    ma60_240 = round(float(c60.mean()), 1)
        except:
            ma60_240 = None

        return {
            'signal':    signal,
            'action':    action,
            'price':     round(price, 1),
            'hold_days': hold_days,
            'ma5':       ma5,
            'ma10':      ma10,
            'ma60_240':  ma60_240,
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
  --bg:      #0d1b2a;
  --card:    #132338;
  --card2:   #0f1e30;
  --border:  #1e3a5f;
  --text1:   #e8f0fe;
  --text2:   #4a6fa5;
  --text3:   #2d5480;
  --accent:  #1a73e8;
  --green:   #34c759;
  --yellow:  #ffd60a;
  --red:     #ff453a;
  --radius:  14px;
  --radius-s:8px;
}
* { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }
body { font-family:-apple-system,"Helvetica Neue",sans-serif; background:var(--bg); color:var(--text1); min-height:100vh; padding-bottom:60px; }
.wrap { max-width:860px; margin:0 auto; padding:0 20px; }
.header { padding:40px 0 10px; }
.header-sub { font-size:11px; color:var(--text2); letter-spacing:0.1em; text-transform:uppercase; margin-bottom:6px; }
.header h1 { font-size:26px; font-weight:800; color:var(--text1); letter-spacing:-0.03em; }
.sync-bar { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding-bottom:10px; }
.btn-sync { padding:5px 12px; border-radius:12px; border:1px solid var(--border); background:transparent; color:var(--text2); font-size:12px; cursor:pointer; font-family:inherit; }
.sync-st { font-size:11px; color:var(--text3); }
.tabs-wrap { margin-bottom:10px; overflow-x:auto; scrollbar-width:none; }
.tabs-wrap::-webkit-scrollbar { display:none; }
.tabs { display:flex; gap:6px; width:max-content; }
.tab { padding:6px 14px; border-radius:16px; font-size:13px; font-weight:500; cursor:pointer; border:1px solid var(--border); color:var(--text2); background:var(--card); white-space:nowrap; }
.tab.active { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:700; }
.panel { display:none; }
.panel.active { display:block; }
.card { background:var(--card); border-radius:var(--radius); border:1px solid var(--border); overflow:hidden; }
.gname-wrap { padding:14px 16px 12px; }
.gname { width:100%; background:transparent; border:none; font-size:16px; font-weight:700; color:var(--text1); font-family:inherit; }
.gname:focus { outline:none; }
.sep { height:1px; background:var(--border); }
.add-row { display:flex; gap:8px; padding:10px 16px; }
.add-inp { flex:1; background:var(--card2); border:1px solid var(--border); border-radius:var(--radius-s); padding:9px 12px; color:var(--text1); font-size:14px; font-family:inherit; }
.add-inp:focus { outline:none; border-color:var(--accent); }
.add-inp::placeholder { color:var(--text3); }
.btn-add { padding:9px 16px; border-radius:var(--radius-s); border:none; background:var(--accent); color:#fff; font-size:14px; font-weight:700; cursor:pointer; font-family:inherit; white-space:nowrap; }
.btn-add:active { opacity:.7; }

/* 用 table 取代 grid，自動分配欄寬 */
table { width:100%; border-collapse:collapse; }
thead tr { border-top:1px solid var(--border); }
thead th {
  padding:8px 8px;
  font-size:11px; color:var(--text3);
  font-weight:700; letter-spacing:0.05em;
  text-transform:uppercase;
  text-align:right;
  white-space:nowrap;
}
thead th:first-child { text-align:left; }
thead th:nth-child(2) { text-align:left; }
tbody tr { border-top:1px solid var(--border); }
tbody tr:hover { background:rgba(255,255,255,0.02); }
tbody td { padding:11px 8px; vertical-align:middle; white-space:nowrap; }

/* 代號欄 */
.td-id { text-align:left; }
.id-num { font-size:16px; font-weight:800; color:var(--text1); }

/* 收盤價欄 */
.td-price { text-align:left; }
.price-val { font-size:16px; font-weight:700; color:var(--text1); }

/* 訊號欄 */
.td-sig { text-align:left; }
.sig-row { display:flex; align-items:center; gap:6px; white-space:nowrap; }
.sig-emoji { font-size:16px; }
.sig-action { font-size:15px; font-weight:700; }
.sig-days { font-size:12px; color:var(--text2); margin-left:2px; }
.sig-g { color:var(--green); }
.sig-y { color:var(--yellow); }
.sig-r { color:var(--red); }
.sig-w { color:var(--text1); }

/* 均線欄 */
.td-ma { text-align:right; }
.ma-val { font-size:16px; font-weight:700; }
.above { color:var(--green); }
.below { color:#ff6b6b; }
.na    { color:var(--text3); font-size:13px; }

/* 刪除欄 */
.td-del { text-align:right; width:36px; }
.btn-del { width:24px; height:24px; border-radius:50%; border:none; background:rgba(255,69,58,.15); color:var(--red); font-size:13px; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; }
.btn-del:active { background:rgba(255,69,58,.35); }

.empty { padding:28px 16px; text-align:center; color:var(--text3); font-size:14px; }
.loading { padding:20px 16px; text-align:center; color:var(--text3); font-size:14px; }
.err { padding:12px 16px; color:var(--red); font-size:14px; }
.bot { display:flex; align-items:center; justify-content:space-between; padding:12px 16px; border-top:1px solid var(--border); }
.upd { font-size:11px; color:var(--text3); }
.btn-scan { padding:10px 24px; border-radius:20px; border:none; background:var(--green); color:#000; font-size:14px; font-weight:800; cursor:pointer; font-family:inherit; }
.btn-scan:active { opacity:.7; }
.btn-scan:disabled { background:var(--card2); color:var(--text3); cursor:not-allowed; }
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="header-sub">2 日高低點突破系統</div>
    <h1>GA 買賣訊號</h1>
  </div>
  <div class="sync-bar">
    <span class="sync-st" id="syncSt">尚未同步</span>
    <button class="btn-sync" onclick="syncDown()">從雲端載入</button>
    <button class="btn-sync" onclick="syncUp()">儲存至雲端</button>
  </div>
  <div class="tabs-wrap"><div class="tabs" id="tabs"></div></div>
  <div id="panels"></div>
</div>
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
      "<table>"+
        "<thead><tr>"+
          "<th>代號</th><th>收盤價</th><th>訊號／天數</th>"+
          "<th>60MA240</th><th>MA5</th><th>MA10</th><th></th>"+
        "</tr></thead>"+
        "<tbody id=\\"sl"+i+"\\">"+renderRows(g.stocks,i)+"</tbody>"+
      "</table>"+
      "<div class=\\"bot\\">"+
        "<span class=\\"upd\\" id=\\"ut"+i+"\\"></span>"+
        "<button class=\\"btn-scan\\" id=\\"sb"+i+"\\" onclick=\\"scan("+i+")\\">掃描訊號</button>"+
      "</div>"+
      "</div>";
    pe.appendChild(p);
  });
}
function maClass(price,ma){
  if(ma==null||price==null) return "na";
  return price>=ma?"above":"below";
}
function maVal(ma){ return ma!=null?ma:"—"; }
function renderRows(stocks,gi){
  if(!stocks||stocks.length===0)
    return "<tr><td colspan=\\"7\\"><div class=\\"empty\\">尚未新增股票</div></td></tr>";
  return stocks.map(function(s,si){
    var sig=s.signal||"⬜", act=s.action||"—";
    var price=s.price!=null?s.price:"—";
    var days=s.hold_days>0?" "+s.hold_days+"天":"";
    var cls=sig==="🟢"?"sig-g":sig==="🟡"?"sig-y":sig==="🔴"?"sig-r":"sig-w";
    var m240c=maClass(s.price,s.ma60_240);
    var m5c=maClass(s.price,s.ma5);
    var m10c=maClass(s.price,s.ma10);
    return "<tr>"+
      "<td class=\\"td-id\\"><span class=\\"id-num\\">"+esc(s.id)+"</span></td>"+
      "<td class=\\"td-price\\"><span class=\\"price-val\\">"+price+"</span></td>"+
      "<td class=\\"td-sig\\"><div class=\\"sig-row\\">"+
        "<span class=\\"sig-emoji\\">"+sig+"</span>"+
        "<span class=\\"sig-action "+cls+"\\">"+act+"</span>"+
        "<span class=\\"sig-days\\">"+days+"</span>"+
      "</div></td>"+
      "<td class=\\"td-ma\\"><span class=\\"ma-val "+m240c+"\\">"+maVal(s.ma60_240)+"</span></td>"+
      "<td class=\\"td-ma\\"><span class=\\"ma-val "+m5c+"\\">"+maVal(s.ma5)+"</span></td>"+
      "<td class=\\"td-ma\\"><span class=\\"ma-val "+m10c+"\\">"+maVal(s.ma10)+"</span></td>"+
      "<td class=\\"td-del\\"><button class=\\"btn-del\\" onclick=\\"delS("+gi+","+si+")\\">&#xd7;</button></td>"+
      "</tr>";
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
  document.getElementById("sl"+i).innerHTML="<tr><td colspan=\\"7\\"><div class=\\"loading\\">查詢中，請稍候...</div></td></tr>";
  fetch("/api/batch?ids="+encodeURIComponent(ids))
    .then(function(r){return r.json();})
    .then(function(data){
      stocks.forEach(function(s){
        var r=data[s.id];
        if(r){ s.signal=r.signal; s.action=r.action; s.price=r.price; s.hold_days=r.hold_days; s.ma5=r.ma5; s.ma10=r.ma10; s.ma60_240=r.ma60_240; }
      });
      saveL();
      document.getElementById("sl"+i).innerHTML=renderRows(stocks,i);
      var now=new Date();
      document.getElementById("ut"+i).textContent="更新 "+now.getFullYear()+"/"+(now.getMonth()+1)+"/"+now.getDate()+" "+now.getHours()+":"+String(now.getMinutes()).padStart(2,"0");
      btn.disabled=false; btn.innerHTML="掃描訊號";
    })
    .catch(function(){
      document.getElementById("sl"+i).innerHTML="<tr><td colspan=\\"7\\"><div class=\\"err\\">連線失敗，請稍後再試</div></td></tr>";
      btn.disabled=false; btn.innerHTML="掃描訊號";
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
