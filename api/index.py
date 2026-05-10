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
    return 'GA Stock API is running.'

if __name__ == '__main__':
    app.run()
