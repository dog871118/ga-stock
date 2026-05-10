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
    background: #0f172a;
    color: #e2e8f0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
  }
  h1 { font-size: 1.8rem; margin-bottom: 8px; color: #f8fafc; }
  .subtitle { color: #94a3b8; font-size: 0.9rem; margin-bottom: 32px; }
  .card {
    background: #1e293b;
    border-radius: 16px;
    padding: 28px;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.4);
  }
  .input-row {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
  }
  input {
    flex: 1;
    padding: 12px 16px;
    border-radius: 10px;
    border: 1px solid #334155;
    background: #0f172a;
    color: #f1f5f9;
    font-size: 1rem;
    outline: none;
  }
  input:focus { border-color: #6366f1; }
  button {
    padding: 12px 20px;
    border-radius: 10px;
    border: none;
    background: #6366f1;
    color: white;
    font-size: 1rem;
    cursor: pointer;
    font-weight: 600;
    transition: background 0.2s;
  }
  button:hover { background: #4f46e5; }
  button:disabled { background: #334155; cursor: not-allowed; }
  .result {
    text-align: center;
    padding: 20px;
    border-radius: 12px;
    background: #0f172a;
    display: none;
  }
  .signal-icon { font-size: 3rem; margin-bottom: 8px; }
  .action { font-size: 1.5rem; font-weight: 700; margin-bottom: 12px; }
  .info { color: #94a3b8; font-size: 0.9rem; line-height: 1.8; }
  .error { color: #f87171; text-align: center; padding: 12px; display: none; }
  .loading { text-align: center; color: #94a3b8; padding: 12px; display: none; }
  .hint { color: #475569; font-size: 0.8rem; margin-top: 12px; text-align: center; }
</style>
</head>
<body>
<h1>📈 GA 買賣訊號</h1>
<p class="subtitle">2日高低點突破系統</p>
<div class="card">
  <div class="input-row">
    <input type="text" id="stockInput" placeholder="輸入股票代號，如 2330" maxlength="10">
    <button id="checkBtn" onclick="checkStock()">查詢</button>
  </div>
  <div class="loading" id="loading">⏳ 查詢中，請稍候...</div>
  <div class="error" id="error"></div>
  <div class="result" id="result">
    <div class="signal-icon" id="signalIcon"></div>
    <div class="action" id="actionText"></div>
    <div class="info" id="infoText"></div>
  </div>
  <p class="hint">上市輸入代號如 2330，上櫃輸入如 3550.TWO</p>
</div>
<script>
  document.getElementById('stockInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') checkStock();
  });

  async function checkStock() {
    const id = document.getElementById('stockInput').value.trim();
    if (!id) return;
    document.getElementById('result').style.display = 'none';
    document.getElementById('error').style.display = 'none';
    document.getElementById('loading').style.display = 'block';
    document.getElementById('checkBtn').disabled = true;
    try {
      const res = await fetch('/api/check?id=' + encodeURIComponent(id));
      const data = await res.json();
      document.getElementById('loading').style.display = 'none';
      document.getElementById('checkBtn').disabled = false;
      if (data.error) {
        document.getElementById('error').textContent = '❌ ' + data.error;
        document.getElementById('error').style.display = 'block';
      } else {
        document.getElementById('signalIcon').textContent = data.signal;
        document.getElementById('actionText').textContent = data.action;
        document.getElementById('infoText').innerHTML =
          '現價：<strong>' + data.price + '</strong> 元<br>' +
          (data.hold_days > 0 ? '持有天數：<strong>' + data.hold_days + '</strong> 天' : '今日訊號');
        document.getElementById('result').style.display = 'block';
      }
    } catch(e) {
      document.getElementById('loading').style.display = 'none';
      document.getElementById('checkBtn').disabled = false;
      document.getElementById('error').textContent = '❌ 連線失敗，請稍後再試';
      document.getElementById('error').style.display = 'block';
    }
  }
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run()
