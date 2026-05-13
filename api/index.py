from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd

app = Flask(__name__)
CORS(app)

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


def get_signals(stock_id):
    try:
        ticker = stock_id if stock_id.endswith(".TWO") else stock_id + ".TW"

        # 日線
        df_d = yf.download(ticker, period="40d",
                           auto_adjust=True, progress=False)
        if df_d.empty or len(df_d) < 5:
            return None

        if isinstance(df_d.columns, pd.MultiIndex):
            close_d = df_d['Close'].iloc[:, 0].dropna()
        else:
            close_d = df_d['Close'].dropna()

        close_d  = close_d.iloc[-20:]
        price    = round(float(close_d.iloc[-1]), 2)
        d_signal, d_action, d_days = calc_signal(close_d)

        # 週線
        df_w = yf.download(ticker, period="60wk",
                           interval="1wk",
                           auto_adjust=True, progress=False)
        if df_w.empty or len(df_w) < 5:
            w_signal, w_action, w_days = '⬜', '空手', 0
        else:
            if isinstance(df_w.columns, pd.MultiIndex):
                close_w = df_w['Close'].iloc[:, 0].dropna()
            else:
                close_w = df_w['Close'].dropna()
            close_w  = close_w.iloc[-20:]
            w_signal, w_action, w_days = calc_signal(close_w)

        return {
            'price':    price,
            'daily':   {'signal': d_signal, 'action': d_action, 'days': d_days},
            'weekly':  {'signal': w_signal, 'action': w_action, 'days': w_days},
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
        return jsonify({'error': '查無資料，請確認代號'}), 404
    return jsonify(result)

@app.route('/')
def home():
    return 'GA Stock API is running.'

if __name__ == '__main__':
    app.run()
