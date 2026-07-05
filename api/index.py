# 東東.STOCK - 即時追蹤 + 每日戰報整合版（後端與原 GA Stock v8 相同）
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

        # 昨日收盤價（T-1）、前日收盤價（T-2）
        prev_price  = round(float(close_d.iloc[-2]), 2) if len(close_d) >= 2 else None
        prev2_price = round(float(close_d.iloc[-3]), 2) if len(close_d) >= 3 else None

        # 接近均線判斷（3%以內）
        def near(p, ma):
            if p and ma:
                return abs(p - ma) / ma <= 0.03
            return False

        # ── 量能欄位（主升段啟動分用）──
        vol_today = None; vol_ma5v = None; vol_ma20v = None
        vol_ratio = None; vol_cv10 = None
        vol_3d_inc = False; vol_5d_slope_up = False
        vol_hollow = False; vol_no_spike = False
        high_52w = None; new_high_52w = False
        low_52w = None; gain_52w = None   # 距52週低點漲幅
        low_60d = None; gain_60d = None   # 距60日低點漲幅
        ma60_bias = None                   # 距MA60乖離率
        close_pos = None  # 今日收盤在日高低間的位置 0~1
        red_k_10 = 0; black_k_10 = 0; long_upper_shadow_10 = 0
        ma5_slope = None; ma10_slope = None; ma20_slope = None
        rs_20 = None  # 近20日相對強度 vs 大盤

        try:
            # 抓 Volume（用 df_d 已有）
            if isinstance(df_d.columns, pd.MultiIndex):
                vol_s = df_d['Volume'].iloc[:, 0].dropna()
                high_s = df_d['High'].iloc[:, 0].dropna()
                low_s  = df_d['Low'].iloc[:, 0].dropna()
                open_s = df_d['Open'].iloc[:, 0].dropna()
            else:
                vol_s  = df_d['Volume'].dropna()
                high_s = df_d['High'].dropna()
                low_s  = df_d['Low'].dropna()
                open_s = df_d['Open'].dropna()

            # 盤中同步截斷
            min_len = min(len(close_d), len(vol_s), len(high_s), len(low_s))
            vol_s  = vol_s.iloc[-min_len:]
            high_s = high_s.iloc[-min_len:]
            low_s  = low_s.iloc[-min_len:]
            open_s = open_s.iloc[-min_len:]

            if len(vol_s) >= 5:
                vol_today  = int(vol_s.iloc[-1])
                vol_ma5v   = float(vol_s.iloc[-5:].mean())
                vol_ma20v  = float(vol_s.iloc[-20:].mean()) if len(vol_s) >= 20 else float(vol_s.mean())
                vol_ratio  = round(vol_today / vol_ma20v, 2) if vol_ma20v > 0 else None

                # 近10日量 CV（變異係數：越低量縮越穩定）
                if len(vol_s) >= 10:
                    v10 = vol_s.iloc[-10:].astype(float)
                    mean10 = float(v10.mean())
                    vol_cv10 = round(float(v10.std()) / mean10, 3) if mean10 > 0 else None

                # 近3日量遞增
                if len(vol_s) >= 3:
                    vol_3d_inc = (float(vol_s.iloc[-1]) > float(vol_s.iloc[-2]) > float(vol_s.iloc[-3]))

                # 五日均量向上（最近5日均 > 前5日均）
                if len(vol_s) >= 10:
                    vol_5d_slope_up = float(vol_s.iloc[-5:].mean()) > float(vol_s.iloc[-10:-5].mean())

                # 凹洞量判斷
                # 定義：過去20日有高峰量，中間量縮到低點，最近3日出量回升但未超過高峰50%
                if len(vol_s) >= 20:
                    v20 = vol_s.iloc[-20:].astype(float).values
                    peak_vol = float(v20[:-5].max()) if len(v20) > 5 else float(v20.max())
                    trough_vol = float(v20[-10:-3].min()) if len(v20) >= 13 else float(v20.min())
                    recent_avg = float(vol_s.iloc[-3:].mean())
                    vol_hollow = (
                        peak_vol > 0 and
                        trough_vol < peak_vol * 0.6 and   # 有明顯量縮
                        recent_avg > trough_vol * 1.3 and  # 出量回升30%以上
                        recent_avg < peak_vol * 0.55       # 但未達高峰量55%（慢慢出量）
                    )

                # 今日沒有爆量（量比 < 2.0）
                vol_no_spike = (vol_ratio is not None and vol_ratio < 2.0)

            # 52週新高（抓1年資料）
            try:
                df_1y = yf.download(ticker, period='1y', auto_adjust=True, progress=False)
                if not df_1y.empty:
                    if isinstance(df_1y.columns, pd.MultiIndex):
                        c1y = df_1y['Close'].iloc[:, 0].dropna()
                    else:
                        c1y = df_1y['Close'].dropna()
                    if len(c1y) >= 2:
                        high_52w = round(float(c1y.max()), 2)
                        new_high_52w = float(price) >= float(c1y.iloc[:-1].max())
                        low_52w = round(float(c1y.min()), 2)
                        if low_52w > 0:
                            gain_52w = round((float(price) - low_52w) / low_52w * 100, 1)
            except:
                pass

            # 60日低點漲幅 & MA60乖離率
            if len(close_d) >= 20:
                low_60d = round(float(close_d.iloc[-min(60,len(close_d)):].min()), 2)
                if low_60d > 0:
                    gain_60d = round((float(price) - low_60d) / low_60d * 100, 1)
            if ma60d and ma60d > 0:
                ma60_bias = round((float(price) - ma60d) / ma60d * 100, 1)

            # 收盤位置（今日高低間 0~1，越高越強）
            if len(high_s) >= 1 and len(low_s) >= 1:
                h = float(high_s.iloc[-1]); l = float(low_s.iloc[-1])
                if h > l:
                    close_pos = round((float(price) - l) / (h - l), 3)

            # 健康度：近10日紅黑K、上影線
            if len(close_d) >= 10 and len(open_s) >= 10 and len(high_s) >= 10:
                for i in range(-10, 0):
                    c = float(close_d.iloc[i]); o = float(open_s.iloc[i])
                    h = float(high_s.iloc[i]);  l = float(low_s.iloc[i])
                    if c >= o:
                        red_k_10 += 1
                    else:
                        black_k_10 += 1
                    body = abs(c - o)
                    upper = h - max(c, o)
                    if body > 0 and upper / body > 0.5:
                        long_upper_shadow_10 += 1

            # 均線斜率（用近5日vs前5日均線比較）
            if len(close_d) >= 10:
                ma5_slope  = round((float(close_d.iloc[-5:].mean()) - float(close_d.iloc[-10:-5].mean())) / float(close_d.iloc[-10:-5].mean()) * 100, 3) if len(close_d) >= 10 else None
            if len(close_d) >= 20:
                ma10_slope = round((float(close_d.iloc[-10:].mean()) - float(close_d.iloc[-20:-10].mean())) / float(close_d.iloc[-20:-10].mean()) * 100, 3)
            if len(close_d) >= 40:
                ma20_slope = round((float(close_d.iloc[-20:].mean()) - float(close_d.iloc[-40:-20].mean())) / float(close_d.iloc[-40:-20].mean()) * 100, 3)

            # RS 近20日相對強度（抓大盤 ^TWII）
            try:
                df_tw = yf.download('^TWII', period='60d', auto_adjust=True, progress=False)
                if not df_tw.empty:
                    if isinstance(df_tw.columns, pd.MultiIndex):
                        tw_c = df_tw['Close'].iloc[:, 0].dropna()
                    else:
                        tw_c = df_tw['Close'].dropna()
                    if len(tw_c) >= 20 and len(close_d) >= 20:
                        stock_ret = (float(close_d.iloc[-1]) / float(close_d.iloc[-20]) - 1) * 100
                        mkt_ret   = (float(tw_c.iloc[-1])   / float(tw_c.iloc[-20])   - 1) * 100
                        rs_20 = round(stock_ret - mkt_ret, 2)
            except:
                pass

        except Exception as e:
            pass  # 量能計算失敗不影響主要訊號

        return {
            'price':      price,
            'prev_price': prev_price,
            'prev2_price': prev2_price,
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
            # 主升段啟動分所需欄位
            'vol_today':        vol_today,
            'vol_ma5v':         round(vol_ma5v) if vol_ma5v else None,
            'vol_ma20v':        round(vol_ma20v) if vol_ma20v else None,
            'vol_ratio':        vol_ratio,
            'vol_cv10':         vol_cv10,
            'vol_3d_inc':       vol_3d_inc,
            'vol_5d_slope_up':  vol_5d_slope_up,
            'vol_hollow':       vol_hollow,
            'vol_no_spike':     vol_no_spike,
            'high_52w':         high_52w,
            'new_high_52w':     new_high_52w,
            'low_52w':          low_52w,
            'gain_52w':         gain_52w,
            'low_60d':          low_60d,
            'gain_60d':         gain_60d,
            'ma60_bias':        ma60_bias,
            'close_pos':        close_pos,
            'red_k_10':         red_k_10,
            'black_k_10':       black_k_10,
            'long_upper_shadow_10': long_upper_shadow_10,
            'ma5_slope':        ma5_slope,
            'ma10_slope':       ma10_slope,
            'ma20_slope':       ma20_slope,
            'rs_20':            rs_20,
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
        try:
            data = get_signals(sid)
            if data:
                result[sid] = data
        except Exception:
            pass  # 單支股票失敗，略過繼續查下一支
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

@app.route('/api/report-load', methods=['GET'])
def report_load():
    try:
        r = http_requests.get(GAS_ENDPOINT, params={'action': 'loadreport'}, timeout=20)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/report-save', methods=['POST'])
def report_save():
    try:
        report = request.json.get('report', '')
        r = http_requests.post(GAS_ENDPOINT, data={'action': 'savereport', 'payload': report}, timeout=30)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/market-load', methods=['GET'])
def market_load():
    try:
        r = http_requests.get(GAS_ENDPOINT, params={'action': 'loadmarket'}, timeout=20)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/market-save', methods=['POST'])
def market_save():
    try:
        market = request.json.get('market', '')
        r = http_requests.post(GAS_ENDPOINT, data={'action': 'savemarket', 'payload': market}, timeout=30)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>東東.STOCK</title>
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
/* 模式切換：即時追蹤 / 每日戰報 */
.mode-switch { display: flex; gap: 6px; margin-bottom: 8px; }
.mode-btn {
  flex: 1; padding: 8px; font-size: 14px; font-weight: 700;
  background: #132338; border: 1px solid #1e3a5f; border-radius: 10px;
  color: #7aa8d0; cursor: pointer; font-family: inherit;
}
.mode-btn.active { background: #38bdf8; color: #04223a; border-color: #38bdf8; }
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
.c-buy  { color: #ff453a; }   /* 台股：買進=漲=紅 */
.c-hold { color: #ffd60a; }
.c-sell { color: #30d158; }   /* 台股：賣出=跌=綠 */
.c-idle { color: #ffffff; }
.ma-up  { color: #ff453a; }   /* 站上均線=偏多=紅 */
.ma-dn  { color: #30d158; }   /* 跌破均線=偏空=綠 */
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
.card { position: relative; }
.card-del { position: absolute; top: 8px; right: 10px; background: none; border: none; color: #7aa8d0; font-size: 18px; cursor: pointer; padding: 2px 4px; line-height: 1; }
.card-del:active { color: #ff453a; }
.card-down { border-color: #0e6b6b; background: #0e2b2b; }
.tg-idle { background: rgba(122,168,208,.15); color: #7aa8d0; }
.ma-meta b { font-variant-numeric: tabular-nums; }
.tbl-hdr { display: none !important; }
/* ===== 每日戰報樣式 ===== */
.rpt-date { font-size: 12px; color: #7aa8d0; padding: 0 14px 4px; }
.rpt-src { font-size: 11px; padding: 0 14px 8px; }
.rpt-src.live { color: #34c759; } .rpt-src.cache { color: #ff9f0a; }
.card {
  background: #132338; border: 1px solid #1e3a5f; border-radius: 12px;
  padding: 11px 13px; margin: 0 14px 9px;
}
.card-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-stk { display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; }
.card-nm { font-size: 16px; font-weight: 700; color: #ffffff; }
.card-cd { font-size: 11px; color: #38bdf8; font-variant-numeric: tabular-nums; }
.card-px { font-size: 18px; font-weight: 800; color: #ffd60a; font-variant-numeric: tabular-nums; }
.card-meta { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px; color: #7aa8d0; }
.card-meta b { color: #ffffff; font-weight: 600; }
.tg { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 5px; font-weight: 700; }
.tg-buy { background: rgba(255,69,58,.18); color: #ff453a; }
.tg-sell { background: rgba(48,209,88,.18); color: #30d158; }
.tg-hold { background: rgba(255,214,10,.18); color: #ffd60a; }
.tg-go { background: rgba(56,189,248,.18); color: #38bdf8; }
.tg-rise { background: rgba(255,214,10,.22); color: #ffd60a; }
.tg-warn { background: rgba(255,159,10,.18); color: #ff9f0a; }
.ov { background: #132338; border: 1px solid #1e3a5f; border-radius: 14px; padding: 14px; margin: 0 14px 12px; }
.ov-bias { font-size: 22px; font-weight: 800; text-align: center; margin-bottom: 12px; }
.ov-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 8px; }
.ov-stat { background: #0d1b2a; border: 1px solid #1e3a5f; border-radius: 10px; padding: 9px 11px; }
.ov-k { font-size: 11px; color: #7aa8d0; } .ov-v { font-size: 20px; font-weight: 800; }
.ov-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.ov-chip { font-size: 11px; background: #0d1b2a; border: 1px solid #1e3a5f; color: #ffd60a; padding: 2px 8px; border-radius: 6px; }
.rtoggle { display: flex; gap: 6px; padding: 0 14px; margin-bottom: 10px; }
.rtoggle button { flex: 1; background: #132338; border: 1px solid #1e3a5f; color: #7aa8d0; font-family: inherit; font-size: 13px; font-weight: 700; padding: 8px; border-radius: 9px; cursor: pointer; }
.rtoggle button.on { background: rgba(56,189,248,.16); border-color: #38bdf8; color: #38bdf8; }
.rpane { display: none; } .rpane.on { display: block; }
.pick { background: #0d1b2a; border: 1px solid #1e3a5f; border-radius: 9px; padding: 8px 10px; margin-top: 8px; }
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
.bottomnav{position:fixed;bottom:0;left:0;right:0;z-index:120;display:flex;max-width:540px;margin:0 auto;background:#0a1a2e;border-top:1px solid #1e3a5f;padding:6px 2px calc(6px + env(safe-area-inset-bottom));}
.bottomnav button{flex:1;background:none;border:none;color:#7aa8d0;font-size:10.5px;font-family:inherit;padding:5px 1px;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;border-radius:8px;}
.bottomnav button .ic{font-size:17px;line-height:1;}
.bottomnav button.on{color:#38bdf8;background:rgba(56,189,248,.12);}
.imp-bar{padding:8px 14px 4px;}
.imp-btn{width:100%;background:#132338;border:1px solid #1e3a5f;color:#38bdf8;font-family:inherit;font-size:13px;font-weight:700;padding:10px;border-radius:10px;cursor:pointer;}
.imp-panel{margin-top:8px;}
.imp-box{width:100%;height:90px;background:#132338;border:1px solid #1e3a5f;border-radius:10px;color:#cfe0f0;font-size:12px;padding:9px;font-family:monospace;box-sizing:border-box;}
.imp-do{margin-top:8px;width:100%;background:#38bdf8;color:#04223a;border:none;border-radius:10px;padding:10px;font-size:14px;font-weight:700;cursor:pointer;}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-top">
    <div class="logo">東東.STOCK</div>
    <div class="hdr-btns" id="trackBtns">
      <button class="hbtn" id="btnLoad" onclick="loadCloud()">⬇ 載雲端</button>
      <button class="hbtn" id="btnSave" onclick="saveCloud()">↑ 存雲端</button>
      <button class="hbtn" onclick="toggleHist()">≡ 歷史</button>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
</div>

<div class="main" id="main"></div>
<div class="main" id="rptMain" style="display:none"></div>
<div class="main" id="mktMain" style="display:none"></div>

<nav class="bottomnav" id="bottomnav">
  <button data-view="大盤" onclick="selectView('大盤')"><span class="ic">🌡</span>大盤</button>
  <button data-view="track" class="on" onclick="selectView('track')"><span class="ic">📈</span>自選</button>
  <button data-view="市場總覽" onclick="selectView('市場總覽')"><span class="ic">📊</span>總覽</button>
  <button data-view="持股現況" onclick="selectView('持股現況')"><span class="ic">💼</span>持股</button>
  <button data-view="今日精選" onclick="selectView('今日精選')"><span class="ic">⭐</span>精選</button>
  <button data-view="早期族群" onclick="selectView('早期族群')"><span class="ic">🌱</span>早期</button>
  <button data-view="明日操作" onclick="selectView('明日操作')"><span class="ic">🎯</span>明日</button>
</nav>

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
const SCORE_KEY = 'ga_scores_v1';  // 儲存每支股票上次掃描的分數
const DN = ['自選群組1','自選群組2','自選群組3','自選群組4','自選群組5','自選群組6','自選群組7','自選群組8'];
const SPECIAL_GROUPS = [
  { name: '均線買點', idx: 5 },
  { name: '回踩買點', idx: 6 },
  { name: '訊號異動', idx: 7 },
];

function lgr() {
  try {
    const d=JSON.parse(localStorage.getItem(GK));
    // 已是8群組 → 直接用
    if(d && d.length===8) return d;
    // 舊版4群組（你原本的自選）→ 保留前4個，後面補4個空群組，湊成8個
    if(d && d.length>=1 && d.length<8){
      const out = d.slice(0,8);
      for(let i=out.length;i<8;i++) out.push({name:DN[i],stocks:[]});
      return out;
    }
    // 更舊版5群組 → 取前4，補到8
    if(d && d.length>8) return d.slice(0,8);
  } catch(e){}
  return DN.map(n=>({name:n,stocks:[]}));
}
function allGroups() {
  return [
    ...groups,
    { name:'買進訊號', stocks:[], special:'buy' },
    { name:'賣出訊號', stocks:[], special:'sell' },
    { name:'持有訊號', stocks:[], special:'hold' },
    { name:'空手訊號', stocks:[], special:'idle' },
    { name:'訊號異動', stocks:[], special:'change' },
    { name:'趨勢前20',  stocks:[], special:'rank_swing' },
    { name:'時機前20',  stocks:[], special:'rank_short' },
    { name:'5日線買點', stocks:[], special:'near5' },
    { name:'月線買點', stocks:[], special:'near20' },
    { name:'季線買點', stocks:[], special:'near60' },
    { name:'回踩買點', stocks:[], special:'down' },
    { name:'創新高',   stocks:[], special:'newhigh' },
    { name:'本日漲停', stocks:[], special:'limitup' },
    { name:'本日跌停', stocks:[], special:'limitdown' },
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
// ── 分數記錄：每次掃描後把最新分數存起來，下次掃描時當昨日分數 ──
function loadPrevScores() {
  try { return JSON.parse(localStorage.getItem(SCORE_KEY)||'{}'); } catch(e){ return {}; }
}
function saveScores() {
  const d = {};
  groups.slice(0,8).forEach(g => {
    (g.stocks||[]).forEach(s => {
      if (!s.daily) return;
      const sc = calcScore(s);
      d[s.id] = {
        swing: sc ? sc.swing : null,
        short: sc ? sc.short : null,
        date: dk()
      };
    });
  });
  localStorage.setItem(SCORE_KEY, JSON.stringify(d));
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

// ===== 個股評分系統 =====
// 回傳 { swing: 0-100, short: 0-100, swingReasons: [], shortReasons: [] }
function calcScore(s) {
  if (!s || !s.daily) return null;
  const d  = s.daily  || {};
  const w  = s.weekly || { action:'空手', days:0 };
  const dA = d.action  || '空手';
  const wA = w.action  || '空手';
  const dD = d.days    || 0;
  const wD = w.days    || 0;

  // 取大盤溫度（有 MKT 就用，否則預設中性 50）
  let mktSwing = 50, mktShort = 50;
  try {
    if (typeof MKT !== 'undefined' && MKT) {
      const swT = MKT['波段溫度'] || {};
      const shT = MKT['短線溫度'] || {};
      mktSwing = Number(swT['分數'] || 50);
      mktShort = Number(shT['分數'] || 50);
    }
  } catch(e) {}

  let sw = 0, sh = 0;
  const swR = [], shR = [];

  // ── 趨勢健康分（重寫）──────────────────────
  // 核心：趨勢強度 = 均線斜率 + 均線排列 + 週日線持續性 + RS
  // 不再讓「週線買進」優於「週線持有多週」

  // 1. 均線多頭排列（30分）— 最重要，反映趨勢結構
  if (s.ma5 && s.ma20 && s.ma60d) {
    if (s.price > s.ma5 && s.ma5 > s.ma20 && s.ma20 > s.ma60d) {
      sw+=30; swR.push('均線完整多排');
    } else if (s.price > s.ma5 && s.ma5 > s.ma20) {
      sw+=18; swR.push('MA5>MA20多排');
    } else if (s.price > s.ma20) {
      sw+=8;  swR.push('站上MA20');
    } else if (s.price < s.ma60d) {
      sw-=10; swR.push('跌破MA60');
    }
  } else if (s.ma5 && s.ma20) {
    if (s.price > s.ma5 && s.ma5 > s.ma20) { sw+=15; swR.push('MA5>MA20多排'); }
    else if (s.price > s.ma20)              { sw+=6;  swR.push('站上MA20'); }
  }

  // 2. 均線斜率（25分）— 三條均線同時向上才是真趨勢
  {
    let slopeUp = 0;
    if (s.ma5_slope  != null && s.ma5_slope  > 0) slopeUp++;
    if (s.ma10_slope != null && s.ma10_slope > 0) slopeUp++;
    if (s.ma20_slope != null && s.ma20_slope > 0) slopeUp++;
    if      (slopeUp === 3) { sw+=25; swR.push('三線同向上'); }
    else if (slopeUp === 2) { sw+=15; swR.push('雙線向上'); }
    else if (slopeUp === 1) { sw+=5; }
    else                    { sw-=8;  swR.push('均線走平'); }
  }

  // 3. 週日線持續性（25分）— 持有越久代表趨勢越穩
  if (wA==='持有' || wA==='買進') {
    // 週線：持有天數越長越穩定（買進剛翻多不算持久）
    if      (wD >= 8)  { sw+=15; swR.push(`週線持有${wD}週穩`); }
    else if (wD >= 4)  { sw+=12; swR.push(`週線持有${wD}週`); }
    else if (wD >= 1)  { sw+=8;  swR.push(`週線持有${wD}週`); }
    if (wA==='賣出') { sw-=8; swR.push('週線賣出'); }
  } else if (wA==='賣出') { sw-=8; swR.push('週線賣出'); }

  if (dA==='持有' || dA==='買進') {
    if      (dD >= 10) { sw+=10; swR.push(`日線持有${dD}天穩`); }
    else if (dD >= 5)  { sw+=8; }
    else if (dD >= 1)  { sw+=5; }
  } else if (dA==='賣出') { sw-=8; swR.push('日線賣出'); }

  // 4. RS 相對強度（10分）— 持續跑贏大盤才是真強勢
  if (s.rs_20 != null) {
    if      (s.rs_20 >= 10) { sw+=10; swR.push(`RS超強+${s.rs_20}%`); }
    else if (s.rs_20 >= 5)  { sw+=7;  swR.push(`RS強+${s.rs_20}%`); }
    else if (s.rs_20 >= 0)  { sw+=3; }
    else if (s.rs_20 < -5)  { sw-=5;  swR.push('RS落後大盤'); }
  }

  // 5. 大盤波段溫度加權（±5）
  {
    const adj = Math.round((mktSwing - 50) / 10);
    sw += adj;
    if (adj > 0)      swR.push(`大盤偏熱+${adj}`);
    else if (adj < 0) swR.push(`大盤偏冷${adj}`);
  }

  // 6. 創10日新高加成
  if (s.new_high_10) { sw+=5; swR.push('創10日新高'); }

  sw = Math.max(0, Math.min(100, sw));

  // ── 短線時機分 ──────────────────────────────
  // 1. 訊號剛翻轉 (25分)
  const ydA = (s.yesterday && s.yesterday.action) || '';
  if (dA==='買進' && (ydA==='空手'||ydA==='賣出'||ydA==='')) {
    sh+=25; shR.push('剛出現買進訊號');
  } else if (dA==='持有' && dD===1) {
    sh+=18; shR.push('持有第1天');
  } else if (dA==='持有' && dD<=3) {
    sh+=12; shR.push(`持有僅${dD}天`);
  } else if (dA==='買進') {
    sh+=15; shR.push('買進訊號中');
  }

  // 2. 均線買點回踩 (25分)
  let nearPts = 0, nearLbl = '';
  if (s.near_ma5)  { nearPts=Math.max(nearPts,10); nearLbl='靠近MA5'; }
  if (s.near_ma20) { nearPts=Math.max(nearPts,18); nearLbl='靠近MA20'; }
  if (s.near_ma60d){ nearPts=Math.max(nearPts,25); nearLbl='靠近MA60'; }
  if (nearPts > 0 && (dA==='買進'||dA==='持有')) {
    sh+=nearPts; shR.push(nearLbl+'回踩買點');
  }

  // 3. 今日漲跌幅表現 (15分)
  if (s.price && s.prev_price) {
    const pct = (s.price / s.prev_price - 1) * 100;
    if      (pct >  3) { sh+=15; shR.push(`今日強漲+${pct.toFixed(1)}%`); }
    else if (pct >  1) { sh+=8;  shR.push(`今日上漲+${pct.toFixed(1)}%`); }
    else if (pct > -1) { sh+=3;  }
    else if (pct > -3) { sh-=5;  shR.push(`今日下跌${pct.toFixed(1)}%`); }
    else               { sh-=10; shR.push(`今日大跌${pct.toFixed(1)}%`); }
  }

  // 4. 創10日新高 (15分)
  if (s.new_high_10) { sh+=15; shR.push('創10日新高'); }

  // 5. 持有回踩買點（App「回踩買點」的核心邏輯）
  // 持有訊號 + 今日收黑 = 洗盤回踩，隔日反彈機率高
  if (dA==='持有' && s.price && s.prev_price && s.price < s.prev_price) {
    // 單純回踩
    sh += 12; shR.push('持有回踩買點');
    // 同時靠近均線：雙重確認
    if (s.near_ma5 || s.near_ma20 || s.near_ma60d) {
      sh += 8; shR.push('回踩貼近均線');
    }
    // 量縮回踩：洗盤更乾淨
    if (s.vol_ratio != null && s.vol_ratio < 0.8) {
      sh += 5; shR.push('量縮洗盤');
    }
  }

  // 6. 噴出辨識：連買 + 強漲 (加分但也要注意過熱)
  if (dA==='買進' && s.price && s.prev_price) {
    const pct = (s.price / s.prev_price - 1) * 100;
    if (pct > 2) { sh+=10; shR.push('噴出特徵'); }
  }

  // 7. 大盤短線溫度加權 (10分)
  {
    const adj = Math.round((mktShort - 50) / 10);
    sh += adj;
    if (adj > 2)       shR.push(`大盤短線熱+${adj}`);
    else if (adj < -2) shR.push(`大盤短線冷${adj}`);
  }

  sh = Math.max(0, Math.min(100, sh));

  return { swing: sw, short: sh, swingReasons: swR, shortReasons: shR };
}

// 總分（波段 60% + 短線 40%）
function totalScore(s) {
  const sc = calcScore(s);
  if (!sc) return 0;
  return Math.round(sc.swing * 0.6 + sc.short * 0.4);
}

function sortBySignal(arr) {
  return arr.slice().sort((a,b) => {
    const da = a.daily ? sigOrder(a.daily.action) : 4;
    const db = b.daily ? sigOrder(b.daily.action) : 4;
    if (da !== db) return da - db;
    // 同訊號內：總分高的排前面
    return totalScore(b) - totalScore(a);
  });
}

// ===== 本日漲停／跌停（代號來自每日戰報，卡片走與自選相同的 /api/batch 管道）=====
// 這兩組獨立於可編輯群組(1~8)，不會被 9~16 的自動分類掃到
function getLimitCodes(dir){
  let r = (typeof RPT!=='undefined' && RPT) ? RPT : null;
  if(!r){ try{ const s=localStorage.getItem(RPT_KEY); if(s) r=JSON.parse(s); }catch(e){} }
  if(!r) return null;                       // 連戰報都還沒匯入
  const arr = dir==='up' ? (r['漲停']||[]) : (r['跌停']||[]);
  return arr.map(x => typeof x==='string' ? x : (x.t||x.代號||x.id||x.code||'')).filter(Boolean);
}
async function renderLimit(dir){
  renderTabs();
  const title = dir==='up' ? '本日漲停' : '本日跌停';
  const myTab = dir==='up' ? 16 : 17;
  const codes = getLimitCodes(dir);
  const main = document.getElementById('main');
  let rptInfo = '';
  try{ rptInfo = (typeof RPT!=='undefined' && RPT) ? (RPT['日期']||'') : ''; }catch(e){}
  if(codes === null){
    main.innerHTML = `<div class="grp-bar"><div class="grp-name-inp">${title}</div></div>
      <div class="empty">尚未匯入今日戰報，無法取得${dir==='up'?'漲停':'跌停'}清單。<br>
      請先到「總覽 / 持股」分頁貼上今日戰報（V27 複製來），再回到本頁。</div>`;
    return;
  }
  if(codes.length === 0){
    main.innerHTML = `<div class="grp-bar"><div class="grp-name-inp">${title}</div></div>
      <div class="upd-time">資料日期：${rptInfo}</div>
      <div class="empty">今日無${dir==='up'?'漲停':'跌停'}股票</div>`;
    return;
  }
  main.innerHTML = `<div class="grp-bar"><div class="grp-name-inp">${title}（${codes.length} 檔）</div></div>
    <div class="upd-time" id="limUpd">載入中… 0/${codes.length}（資料日期 ${rptInfo}）</div>
    <div class="tbl-hdr">
      <span class="col-id">代號</span><span class="col-price">收盤價</span>
      <span class="col-sig">訊號／均線</span><span class="col-del"></span>
    </div>
    <div id="limList"></div>`;
  const listEl = document.getElementById('limList');
  const updEl  = document.getElementById('limUpd');
  const got = [];
  const CH = 12;                            // 一次抓12檔，邊抓邊顯示
  for(let i=0;i<codes.length;i+=CH){
    if(cur !== myTab) return;               // 使用者切走就停止
    const chunk = codes.slice(i, i+CH);
    try{
      const res = await fetch('/api/batch?ids='+encodeURIComponent(chunk.join(',')));
      const data = await res.json();
      chunk.forEach(full=>{
        const r = data[full] || data[full.toUpperCase()];
        if(r){ got.push({ ...r, id: String(full).split('.')[0] }); }
      });
    }catch(e){}
    const sorted = sortBySignal(got);
    listEl.innerHTML = sorted.map((s,si)=>rc(s, myTab, si, true)).join('');
    if(updEl) updEl.textContent = `載入中… ${Math.min(i+CH,codes.length)}/${codes.length}（資料日期 ${rptInfo}）`;
  }
  if(updEl) updEl.textContent = `資料日期：${rptInfo}　共 ${got.length} 檔　更新：${ts()}`;
  if(got.length===0) listEl.innerHTML = `<div class="empty">查無資料（可能代號已下市或暫停交易）</div>`;
}

// ===== 排行榜 Tab =====
function scoreColor(v) {
  if (v == null) return '#7aa8d0';
  return v >= 75 ? '#ff453a' : v >= 45 ? '#ffd60a' : '#30d158';
}

function momentumLabel(sc) {
  if (sc == null) return '';
  if (sc >= 75) return '🚀強勢啟動';
  if (sc >= 60) return '✅蓄勢向上';
  if (sc >= 45) return '🔄觀察中';
  return '😶偏弱';
}

function renderRanking(type) {
  renderTabs();
  const mainEl = document.getElementById('main');
  // 從群組1~8彙整所有有資料的股票（同代號去重，保留分數最高的）
  const seenIds = {};
  let all = [];
  groups.slice(0,8).forEach((g, gi) => {
    (g.stocks||[]).forEach(s => {
      if (!s.daily) return;
      const sc = calcScore(s);
      const prev = loadPrevScores()[s.id] || {};
      const maxSc = Math.max(sc ? sc.swing : 0, sc ? sc.short : 0);
      if (!seenIds[s.id] || maxSc > seenIds[s.id].maxSc) {
        seenIds[s.id] = { s, gi, sc, prev, maxSc };
      }
    });
  });
  all = Object.values(seenIds);

  // 依類型排序
  let sorted, titleText, emptyText;
  if (type === 'rank_swing') {
    sorted = all.filter(x => x.sc).sort((a,b) => b.sc.swing - a.sc.swing).slice(0,20);
    titleText = '▪ 趨勢健康 前20名';
    emptyText = '請先掃描自選股 1–8 組';
  } else if (type === 'rank_short') {
    sorted = all.filter(x => x.sc).sort((a,b) => b.sc.short - a.sc.short).slice(0,20);
    titleText = '▪ 進場時機 前20名';
    emptyText = '請先掃描自選股 1–8 組';
  } else {
    // 起漲候選：四條件全通過，依 gain_60d（距低點漲幅）由低到高排，位置越低越優先
    sorted = all.filter(x => x.ms).sort((a,b) => b.ms.score - a.ms.score).slice(0,20);
    titleText = '🚀 主升段 前20名';
    emptyText = '請先掃描自選股 1–8 組';
  }

  if (sorted.length === 0) {
    mainEl.innerHTML = `<div class="upd-time" style="margin:16px">${emptyText}</div>`;
    return;
  }

  let h = `<div style="padding:10px 14px 4px;font-size:13px;color:#38bdf8;font-weight:700">${titleText}</div>`;

  sorted.forEach(({s, gi, sc, ms, prev}, rank) => {
    const dA = s.daily ? s.daily.action : '空手';
    const wA = s.weekly ? s.weekly.action : '空手';
    const dD = s.daily ? s.daily.days : 0;

    // 決定顯示的主分數
    let mainScore, prevScore, barColor;
    if (type === 'rank_swing') {
      mainScore = sc ? sc.swing : null;
      prevScore = prev.swing != null ? prev.swing : null;
      barColor = scoreColor(mainScore);
    } else if (type === 'rank_short') {
      mainScore = sc ? sc.short : null;
      prevScore = prev.short != null ? prev.short : null;
      barColor = scoreColor(mainScore);
    } else {
      mainScore = ms ? ms.score : null;
      prevScore = prev.momentum != null ? prev.momentum : null;
      barColor = scoreColor(mainScore);
    }

    // 昨日分數＋變化
    let deltaHtml = '';
    if (prevScore != null && mainScore != null) {
      const delta = mainScore - prevScore;
      if (Math.abs(delta) >= 1) {
        const dColor = delta > 0 ? '#ff453a' : '#30d158';
        const dArrow = delta > 0 ? '▲' : '▼';
        deltaHtml = `<span style="font-size:10.5px;color:${dColor};margin-left:4px">${dArrow}${Math.abs(delta)}</span>`;
      }
    }

    // 狀態標籤（主升段用）
    let statusHtml = '';

    const rankColor = rank === 0 ? '#ffd60a' : rank <= 2 ? '#ff9f0a' : '#7aa8d0';
    const grpName = groups[gi].name;

    h += `<div style="margin:6px 10px;padding:10px 12px;background:rgba(255,255,255,.04);border-radius:10px;border:1px solid rgba(56,189,248,.1)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:13px;font-weight:800;color:${rankColor};min-width:22px">${rank+1}</span>
          <div>
            <span style="font-size:14px;font-weight:700;color:#fff">${s.name||s.id}</span>
            <span style="font-size:11px;color:#38bdf8;margin-left:6px">${s.id}</span>
            <span style="font-size:10px;color:#556a80;margin-left:4px">${grpName}</span>
          </div>
        </div>
        <div style="text-align:right">
          <span style="font-size:16px;font-weight:800;color:${barColor}">${mainScore}</span>
          ${deltaHtml}
          ${statusHtml}
        </div>
      </div>
      <div style="height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden;margin-bottom:5px">
        <div style="width:${mainScore}%;height:100%;background:${barColor};border-radius:3px;transition:width .4s"></div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <span class="tg ${tgCls(dA)}" style="font-size:11px;padding:2px 7px">日 ${dA}${dD>0?' '+dD+(type==='rank_swing'?'天':'天'):''}</span>
          <span class="tg ${tgCls(wA)}" style="font-size:11px;padding:2px 7px;margin-left:4px">週 ${wA}</span>
        </div>
        ${s.price ? `<span style="font-size:13px;font-weight:700;color:#ffd60a">${s.price}</span>` : ''}
      </div>
      ${reasonHtml}

    </div>`;
  });

  mainEl.innerHTML = h;
}

function renderSpecial(type) {
  renderTabs();
  const titles = {
    'buy':'買進訊號','sell':'賣出訊號','hold':'持有訊號','idle':'空手訊號',
    'change':'訊號異動','near5':'5日線買點','near20':'月線買點','near60':'季線買點','down':'回踩買點','newhigh':'創新高'
  };
  const title = titles[type] || type;
  // 收集所有5個群組中符合條件的股票
  const seen = new Set();
  const matched = [];
  groups.forEach(g => {
    (g.stocks||[]).forEach(s => {
      if (!s.daily) return;
      if (seen.has(s.id)) return;
      if (type==='buy') {
        if (s.daily.action==='買進') { matched.push(s); seen.add(s.id); }
      } else if (type==='sell') {
        if (s.daily.action==='賣出') { matched.push(s); seen.add(s.id); }
      } else if (type==='hold') {
        if (s.daily.action==='持有') { matched.push(s); seen.add(s.id); }
      } else if (type==='idle') {
        if (s.daily.action==='空手') { matched.push(s); seen.add(s.id); }
      } else if (type==='near5') {
        if (s.near_ma5) { matched.push(s); seen.add(s.id); }
      } else if (type==='near20') {
        if (s.near_ma20) { matched.push(s); seen.add(s.id); }
      } else if (type==='near60') {
        if (s.near_ma60d) { matched.push(s); seen.add(s.id); }
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
  <div class="upd-time">掃描前8個群組後自動更新</div>`;

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
  if(cur === 8) { renderSpecial('buy');     return; }
  if(cur === 9) { renderSpecial('sell');    return; }
  if(cur === 10){ renderSpecial('hold');    return; }
  if(cur === 11){ renderSpecial('idle');    return; }
  if(cur === 12){ renderSpecial('change');        return; }
  if(cur === 13){ renderRanking('rank_swing');    return; }
  if(cur === 14){ renderRanking('rank_short');    return; }
  if(cur === 16){ renderSpecial('near5');         return; }
  if(cur === 17){ renderSpecial('near20');        return; }
  if(cur === 18){ renderSpecial('near60');        return; }
  if(cur === 19){ renderSpecial('down');          return; }
  if(cur === 20){ renderSpecial('newhigh');       return; }
  if(cur === 21){ renderLimit('up');              return; }
  if(cur === 22){ renderLimit('down');            return; }
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

function tgCls(a){ return a==='買進'?'tg-buy':a==='持有'?'tg-hold':a==='賣出'?'tg-sell':'tg-idle'; }
function rc(s,gi,si,readonly=false){
  const delBtn = readonly ? '' : `<button class="card-del" onclick="del(${gi},${si})">×</button>`;
  if(!s.daily){
    return `<div class="card">
      ${delBtn}
      <div class="card-row"><div class="card-stk"><span class="card-cd">${s.id}</span></div>
        <span style="color:#7aa8d0;font-size:13px">尚未查詢</span></div>
    </div>`;
  }
  const d=s.daily, w=s.weekly||{action:'空手',days:0};
  const dtag=`<span class="tg ${tgCls(d.action)}">日 ${d.action}${d.days>0?' '+d.days+'天':''}</span>`;
  const wtag=`<span class="tg ${tgCls(w.action)}">週 ${w.action}${w.days>0?' '+w.days+'週':''}</span>`;
  const ma=(val,lbl,p,near)=> val
    ? `<span>${lbl} <b class="${maColor(p,val)}">${val}${near?' 😊':''}</b></span>`
    : `<span>${lbl} <b class="ma-na">—</b></span>`;
  const down = d.action==='持有' && s.prev_price && s.price < s.prev_price;
  let chgHtml='';
  if(s.prev_price){
    const diff=Math.round((s.price-s.prev_price)*100)/100;
    const pct=Math.round((s.price/s.prev_price-1)*10000)/100;
    const up=diff>=0;
    chgHtml=`<div style="font-size:12px;font-weight:700;color:${up?'#ff453a':'#30d158'}">${up?'▲':'▼'}${Math.abs(diff)} (${up?'+':''}${pct}%)</div>`;
  }
  return `<div class="card${down?' card-down':''}">
    ${delBtn}
    <div class="card-row">
      <div class="card-stk">
        <span class="card-nm">${s.name||s.id}</span>
        <span class="card-cd">${s.id}</span>
      </div>
      <div style="text-align:right">
        <div class="card-px">${s.price}</div>
        ${chgHtml}
      </div>
    </div>
    <div class="card-meta">${dtag}${wtag}</div>
    <div class="card-meta cl-meta" style="padding-bottom:7px;border-bottom:1px dashed rgba(122,168,208,.18);font-size:13.5px">
      ${s.prev2_price?`<span style="color:#caa84a">前日收 <b style="color:#ffd60a;font-weight:800">${s.prev2_price}</b></span>`:''}
      ${s.prev_price?`<span style="color:#caa84a">昨日收 <b style="color:#ffd60a;font-weight:800">${s.prev_price}</b></span>`:''}
    </div>
    <div class="card-meta ma-meta">
      ${ma(s.ma5,'MA5',s.price,s.near_ma5)}
      ${ma(s.ma10,'MA10',s.price,s.near_ma10)}
      ${ma(s.ma20,'MA20',s.price,s.near_ma20)}
      ${ma(s.ma60d,'MA60',s.price,s.near_ma60d)}
      ${ma(s.ma60k240,'60MA240',s.price,s.near_ma60)}
    </div>
    ${(()=>{
      const sc=calcScore(s);
      if(!sc) return '';
      const prevSc=loadPrevScores()[s.id]||{};
      let swDelta='',shDelta='',totDelta='';
      if(prevSc.swing!=null){const d=sc.swing-prevSc.swing;if(Math.abs(d)>=1){const c=d>0?'#ff453a':'#30d158';swDelta=`<span style="font-size:10px;color:${c};margin-left:3px">${d>0?'▲':'▼'}${Math.abs(d)}</span>`;}}
      if(prevSc.short!=null){const d=sc.short-prevSc.short;if(Math.abs(d)>=1){const c=d>0?'#ff453a':'#30d158';shDelta=`<span style="font-size:10px;color:${c};margin-left:3px">${d>0?'▲':'▼'}${Math.abs(d)}</span>`;}}
      if(prevSc.swing!=null&&prevSc.short!=null){const prevTot=Math.round(prevSc.swing*.6+prevSc.short*.4);const d=Math.round(sc.swing*.6+sc.short*.4)-prevTot;if(Math.abs(d)>=1){const c=d>0?'#ff453a':'#30d158';totDelta=`<span style="font-size:10px;color:${c};margin-left:4px">${d>0?'▲':'▼'}${Math.abs(d)}</span>`;}}
      const tot=Math.round(sc.swing*.6+sc.short*.4);
      const swColor=sc.swing>=75?'#ff453a':sc.swing>=45?'#ffd60a':'#30d158';
      const shColor=sc.short>=75?'#ff453a':sc.short>=45?'#ffd60a':'#30d158';
      const bar=function(v,color){const w=Math.round(v);return '<div style="display:flex;align-items:center;gap:6px"><div style="flex:1;height:7px;background:rgba(255,255,255,.1);border-radius:4px;overflow:hidden"><div style="width:'+w+'%;height:100%;background:'+color+';border-radius:4px"></div></div><span style="width:26px;text-align:right;color:'+color+';font-weight:800;font-size:12px">'+w+'</span></div>';};
      const swR=sc.swingReasons.slice(0,3).join('・');
      const shR=sc.shortReasons.slice(0,3).join('・');
      let html='<div style="margin-top:6px;padding:7px 8px;background:rgba(56,189,248,.07);border-radius:7px;border:1px solid rgba(56,189,248,.15)">';
      html+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">';
      html+='<span style="font-size:11px;color:#38bdf8;font-weight:700">▪ 個股評分</span>';
      html+='<span style="font-size:12px;color:#ff9f0a;font-weight:800">總分 '+tot+totDelta+'</span>';
      html+='</div>';
      html+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 10px;margin-bottom:5px">';
      html+='<div><div style="font-size:11px;color:#7aa8d0;margin-bottom:3px">趨勢健康 <span style="color:'+swColor+';font-weight:800">'+sc.swing+'</span>'+swDelta+'</div>'+bar(sc.swing,swColor)+'</div>';
      html+='<div><div style="font-size:11px;color:#7aa8d0;margin-bottom:3px">進場時機 <span style="color:'+shColor+';font-weight:800">'+sc.short+'</span>'+shDelta+'</div>'+bar(sc.short,shColor)+'</div>';
      html+='</div>';
      if(swR) html+='<div style="font-size:10.5px;color:#a0b4c8;line-height:1.6">趨勢：'+swR+'</div>';
      if(shR) html+='<div style="font-size:10.5px;color:#a0b4c8;line-height:1.6">時機：'+shR+'</div>';
      html+='</div>';
      return html;
    })()}
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
  if(!stocks||stocks.length===0){ return; }
  savePreScanSigs();
  const btn=document.getElementById('scanBtn');
  if(btn){ btn.disabled=true; btn.textContent='查詢中…'; }

  const ids=stocks.map(s=>s.id).join(',');
  try{
    const res=await fetch('/api/batch?ids='+encodeURIComponent(ids),{signal:AbortSignal.timeout(60000)});
    if(!res.ok) throw new Error('HTTP '+res.status);
    const data=await res.json();
    const hs=[];
    stocks.forEach(s=>{
      const r=data[s.id];
      if(r){
        s.price=r.price; s.prev_price=r.prev_price; s.prev2_price=r.prev2_price;
        s.ma5=r.ma5; s.ma10=r.ma10; s.ma20=r.ma20; s.ma60d=r.ma60d; s.ma60k240=r.ma60k240;
        s.near_ma5=r.near_ma5; s.near_ma10=r.near_ma10;
        s.near_ma20=r.near_ma20; s.near_ma60d=r.near_ma60d; s.near_ma60=r.near_ma60;
        s.daily=r.daily; s.weekly=r.weekly; s.yesterday=r.yesterday; s.new_high_10=r.new_high_10;
        s.name=r.name||'';
        s.vol_today=r.vol_today; s.vol_ma5v=r.vol_ma5v; s.vol_ma20v=r.vol_ma20v;
        s.vol_ratio=r.vol_ratio; s.vol_cv10=r.vol_cv10;
        s.vol_3d_inc=r.vol_3d_inc; s.vol_5d_slope_up=r.vol_5d_slope_up;
        s.vol_hollow=r.vol_hollow; s.vol_no_spike=r.vol_no_spike;
        s.high_52w=r.high_52w; s.new_high_52w=r.new_high_52w;
        s.low_52w=r.low_52w; s.gain_52w=r.gain_52w;
        s.low_60d=r.low_60d; s.gain_60d=r.gain_60d;
        s.ma60_bias=r.ma60_bias;
        s.close_pos=r.close_pos;
        s.red_k_10=r.red_k_10; s.black_k_10=r.black_k_10;
        s.long_upper_shadow_10=r.long_upper_shadow_10;
        s.ma5_slope=r.ma5_slope; s.ma10_slope=r.ma10_slope; s.ma20_slope=r.ma20_slope;
        s.rs_20=r.rs_20;
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
    groups[gi].lastUpdate='更新：'+ts(); sgr(); saveSigs(); saveScores();
  }catch(e){
    if(btn){ btn.textContent='✗ 查詢失敗';
      setTimeout(()=>{ if(btn){ btn.disabled=false; btn.textContent='⚡ 掃描'; }},3000);
    }
  }
  if(btn){ btn.disabled=false; btn.textContent='⚡ 掃描'; }
  render();
}

async function autoScan(){
  for(let i=0;i<8;i++){
    if(groups[i].stocks&&groups[i].stocks.length>0){
      cur=i; render();
      try{ await scan(i); }catch(e){}
    }
  }
  const first=groups.findIndex(g=>g.stocks&&g.stocks.length>0);
  cur=first>=0?first:0;
  render();
}

async function saveCloud(){
  const btn=document.getElementById('btnSave');
  btn.textContent='儲存中…'; btn.disabled=true;
  const rows=[];
  groups.slice(0,8).forEach((g,gi)=>{
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
    const res=await fetch('/api/sync-load',{signal:AbortSignal.timeout(45000)});
    const j=await res.json();
    const rows=j.data||[];
    if(rows.length===0){btn.textContent='⬇ 載雲端';btn.disabled=false;cur=0;setTimeout(()=>autoScan(),2000);return;}
    const ng=DN.map((n,i)=>({name:n,stocks:[]}));
    rows.forEach(row=>{
      const gi=parseInt(row[0]);
      if(gi>=0&&gi<8 && row[1]) ng[gi].name=row[1];
    });
    rows.filter(r=>r&&String(r[2]||'').trim()!=='').forEach(row=>{
      const gi=parseInt(row[0]), sid=String(row[2]||'').trim().toUpperCase();
      if(gi>=0&&gi<8 && sid && !ng[gi].stocks.find(s=>s.id===sid)) ng[gi].stocks.push({id:sid});
    });
    groups=ng; sgr(); 
    // 強制清掉舊版 key，避免下次讀到過期資料
    localStorage.removeItem('ga_g_v4');
    cur=0; render();
    btn.textContent='✓ 已載入';
    setTimeout(()=>{btn.textContent='⬇ 載雲端';btn.disabled=false;},1500);
    setTimeout(()=>autoScan(),2000);
  }catch(e){
    btn.textContent='✗ '+(e.message||'失敗'); btn.disabled=false;
    setTimeout(()=>{btn.textContent='⬇ 載雲端';btn.disabled=false;},3000);
    cur=0; setTimeout(()=>autoScan(),2000);
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

/* ============================================================
   每日戰報（讀 V25 推上 GitHub 的 daily_report.json）
   ============================================================ */
const RPT_KEY = 'donG_rpt';
const EMBEDDED_RPT = {
 "產出時間": "2026-06-05 14:30",
 "日期": "2026-06-05",
 "市場總覽": {
  "市場偏向": "偏多 🔴",
  "多方族群數": 19,
  "空方族群數": 7,
  "起漲股數": 54,
  "強勢創新高": 73,
  "均線提醒數": 0,
  "早期族群": [
   "金融保險",
   "造紙",
   "資訊服務",
   "電器電纜",
   "橡膠"
  ]
 },
 "持股現況": [
  {
   "代號": "3481.TW",
   "名稱": "群創",
   "現價": 53.7,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "3504.TW",
   "名稱": "揚明光",
   "現價": 80.9,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "3221.TWO",
   "名稱": "台嘉碩",
   "現價": 57.1,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "5009.TWO",
   "名稱": "榮剛",
   "現價": 37.25,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "3550.TW",
   "名稱": "聯穎",
   "現價": 24.05,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "1477.TW",
   "名稱": "聚陽",
   "現價": 228.0,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "2330.TW",
   "名稱": "台積電",
   "現價": 2365,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "2492.TW",
   "名稱": "華新科",
   "現價": 416.0,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "3450.TW",
   "名稱": "聯鈞",
   "現價": 501.0,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "2408.TW",
   "名稱": "南亞科",
   "現價": 360.0,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "3630.TWO",
   "名稱": "新鉅科",
   "現價": 29.6,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "6116.TW",
   "名稱": "彩晶",
   "現價": 18.45,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "2618.TW",
   "名稱": "長榮航",
   "現價": 37.7,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "2409.TW",
   "名稱": "友達",
   "現價": 27.1,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  },
  {
   "代號": "1303.TW",
   "名稱": "南亞",
   "現價": 104.5,
   "訊號": "待更新",
   "停損": "−",
   "支撐": "−",
   "壓力": "−",
   "目標": "−",
   "均線慣性": "−",
   "明日預測": "−",
   "明日操作": "待 V25 重算"
  }
 ],
 "今日精選": [
  {
   "類型": "觀察",
   "代號": "2855.TW",
   "名稱": "統一證",
   "現價": 55.5,
   "RS60": "92.3%",
   "均線慣性": "10MA慣性",
   "訊號": "買訊",
   "支撐": "50.0～51",
   "停損": 46.5,
   "壓力": "58～59",
   "進場條件": "突破58或回踩51",
   "理由": "族群:金融保險 評分104.5"
  },
  {
   "類型": "★起漲",
   "代號": "2468.TW",
   "名稱": "華經",
   "現價": 44.75,
   "RS60": "77.6%",
   "均線慣性": "慣性偏弱",
   "訊號": "買訊",
   "支撐": "38.0～39.0",
   "停損": 38.5,
   "壓力": "45.0～46.0",
   "進場條件": "突破45.0或回踩39.0",
   "理由": "族群:資訊服務 評分99.0"
  },
  {
   "類型": "★起漲",
   "代號": "1904.TW",
   "名稱": "正隆",
   "現價": 22.3,
   "RS60": "70.9%",
   "均線慣性": "20MA慣性",
   "訊號": "買訊",
   "支撐": "20.0～20.5",
   "停損": 19.0,
   "壓力": "22.5～23.0",
   "進場條件": "突破22.5或回踩20.5",
   "理由": "族群:造紙 評分97.8"
  },
  {
   "類型": "觀察",
   "代號": "2851.TW",
   "名稱": "中再保",
   "現價": 36.85,
   "RS60": "77.3%",
   "均線慣性": "10MA慣性",
   "訊號": "買訊",
   "支撐": "34.0～36.0",
   "停損": 35.0,
   "壓力": "37.0～37.5",
   "進場條件": "突破37.0或回踩36.0",
   "理由": "族群:金融保險 評分93.3"
  },
  {
   "類型": "★起漲",
   "代號": "1611.TW",
   "名稱": "中電",
   "現價": 15.0,
   "RS60": "62.6%",
   "均線慣性": "慣性偏弱",
   "訊號": "買訊",
   "支撐": "12.5～13.0",
   "停損": 11.5,
   "壓力": "15.0～15.5",
   "進場條件": "突破15.0或回踩13.0",
   "理由": "族群:電器電纜 評分92.8"
  }
 ],
 "早期族群": [
  {
   "族群": "金融保險",
   "階段": "🌱蓄勢發動",
   "RS60": 55.0,
   "動能加速": 7.0,
   "精選個股": [
    {
     "代號": "2855.TW",
     "名稱": "統一證",
     "現價": 55.5,
     "支撐": "50.0～51",
     "壓力": "58～59",
     "停損": 46.5,
     "進場": "突破58或回踩51",
     "風報比": "1:0.3",
     "評分": 104.5
    },
    {
     "代號": "2851.TW",
     "名稱": "中再保",
     "現價": 36.85,
     "支撐": "34.0～36.0",
     "壓力": "37.0～37.5",
     "停損": 35.0,
     "進場": "突破37.0或回踩36.0",
     "風報比": "1:0.1",
     "評分": 93.3
    },
    {
     "代號": "2881.TW",
     "名稱": "富邦金",
     "現價": 114.0,
     "支撐": "110～112",
     "壓力": "114～116",
     "停損": 107.0,
     "進場": "突破114或回踩112",
     "風報比": "−",
     "評分": 91.3
    }
   ]
  },
  {
   "族群": "造紙",
   "階段": "👀早期起漲",
   "RS60": 49.3,
   "動能加速": 13.5,
   "精選個股": [
    {
     "代號": "1904.TW",
     "名稱": "正隆",
     "現價": 22.3,
     "支撐": "20.0～20.5",
     "壓力": "22.5～23.0",
     "停損": 19.0,
     "進場": "突破22.5或回踩20.5",
     "風報比": "1:0.1",
     "評分": 97.8
    },
    {
     "代號": "1905.TW",
     "名稱": "華紙",
     "現價": 14.0,
     "支撐": "12.5～13.0",
     "壓力": "14.0～18.5",
     "停損": 12.5,
     "進場": "突破14.0或回踩13.0",
     "風報比": "−",
     "評分": 90.3
    },
    {
     "代號": "1906.TW",
     "名稱": "寶隆",
     "現價": 11.45,
     "支撐": "10.5～11.0",
     "壓力": "12.0～14.0",
     "停損": 10.5,
     "進場": "突破12.0或回踩11.0",
     "風報比": "1:0.6",
     "評分": 70.7
    }
   ]
  },
  {
   "族群": "資訊服務",
   "階段": "👀早期起漲",
   "RS60": 47.9,
   "動能加速": 13.8,
   "精選個股": [
    {
     "代號": "2468.TW",
     "名稱": "華經",
     "現價": 44.75,
     "支撐": "38.0～39.0",
     "壓力": "45.0～46.0",
     "停損": 38.5,
     "進場": "突破45.0或回踩39.0",
     "風報比": "−",
     "評分": 99.0
    },
    {
     "代號": "5203.TW",
     "名稱": "訊連",
     "現價": 72.0,
     "支撐": "66～70",
     "壓力": "75～76",
     "停損": 65.0,
     "進場": "突破75或回踩70",
     "風報比": "1:0.4",
     "評分": 71.0
    },
    {
     "代號": "2453.TW",
     "名稱": "凌群",
     "現價": 61.0,
     "支撐": "58～61",
     "壓力": "66～67",
     "停損": 60.0,
     "進場": "突破66或回踩61",
     "風報比": "1:5.0",
     "評分": 64.1
    }
   ]
  },
  {
   "族群": "電器電纜",
   "階段": "👀早期起漲",
   "RS60": 44.1,
   "動能加速": 17.5,
   "精選個股": [
    {
     "代號": "1611.TW",
     "名稱": "中電",
     "現價": 15.0,
     "支撐": "12.5～13.0",
     "壓力": "15.0～15.5",
     "停損": 11.5,
     "進場": "突破15.0或回踩13.0",
     "風報比": "−",
     "評分": 92.8
    },
    {
     "代號": "1609.TW",
     "名稱": "大亞",
     "現價": 43.0,
     "支撐": "39.5～40.5",
     "壓力": "44.5～45.5",
     "停損": 36.0,
     "進場": "突破44.5或回踩40.5",
     "風報比": "1:0.2",
     "評分": 77.5
    },
    {
     "代號": "1612.TW",
     "名稱": "宏泰",
     "現價": 40.65,
     "支撐": "37.5～38.5",
     "壓力": "42.5～43.5",
     "停損": 36.5,
     "進場": "突破42.5或回踩38.5",
     "風報比": "1:0.4",
     "評分": 75.1
    }
   ]
  },
  {
   "族群": "橡膠",
   "階段": "👀早期起漲",
   "RS60": 41.0,
   "動能加速": 10.2,
   "精選個股": [
    {
     "代號": "2108.TW",
     "名稱": "南帝",
     "現價": 30.9,
     "支撐": "28.0～28.5",
     "壓力": "31.5～32.0",
     "停損": 27.0,
     "進場": "突破31.5或回踩28.5",
     "風報比": "1:0.2",
     "評分": 75.5
    },
    {
     "代號": "2103.TW",
     "名稱": "台橡",
     "現價": 22.25,
     "支撐": "20.0～20.5",
     "壓力": "22.5～23.0",
     "停損": 19.5,
     "進場": "突破22.5或回踩20.5",
     "風報比": "1:0.1",
     "評分": 66.3
    },
    {
     "代號": "2106.TW",
     "名稱": "建大",
     "現價": 18.4,
     "支撐": "17.0～17.5",
     "壓力": "18.5～19.0",
     "停損": 16.0,
     "進場": "突破18.5或回踩17.5",
     "風報比": "−",
     "評分": 53.8
    }
   ]
  }
 ],
 "明日操作": [
  {
   "代號": "3481.TW",
   "名稱": "群創",
   "動作": "⬜觀察",
   "停損": "−",
   "明日": "待 V25 重算"
  },
  {
   "代號": "3504.TW",
   "名稱": "揚明光",
   "動作": "⬜觀察",
   "停損": "−",
   "明日": "待 V25 重算"
  },
  {
   "代號": "3221.TWO",
   "名稱": "台嘉碩",
   "動作": "⬜觀察",
   "停損": "−",
   "明日": "待 V25 重算"
  },
  {
   "代號": "5009.TWO",
   "名稱": "榮剛",
   "動作": "⬜觀察",
   "停損": "−",
   "明日": "待 V25 重算"
  },
  {
   "代號": "3550.TW",
   "名稱": "聯穎",
   "動作": "⬜觀察",
   "停損": "−",
   "明日": "待 V25 重算"
  }
 ],
 "起漲股": [
  {
   "股票": "3312.TW",
   "名稱": "弘憶股",
   "產業": "電子通路",
   "收盤": 73.2,
   "RS60": "97.2%",
   "RS週": "97.4%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 73.0,
   "停損點": 46.5,
   "平台": "無平台"
  },
  {
   "股票": "5285.TW",
   "名稱": "界霖",
   "產業": "半導體",
   "收盤": 99.3,
   "RS60": "95.7%",
   "RS週": "96.8%",
   "均線慣性": "5MA慣性",
   "買賣訊號": "買訊",
   "追價點": 99.0,
   "停損點": 78.0,
   "平台": "10日平台突破(振幅14.5%)"
  },
  {
   "股票": "8454.TW",
   "名稱": "富邦媒",
   "產業": "數位雲端",
   "收盤": 321.0,
   "RS60": "91.2%",
   "RS週": "93.8%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 320.0,
   "停損點": 186.0,
   "平台": "無平台"
  },
  {
   "股票": "9136.TW",
   "名稱": "巨騰-DR",
   "產業": "其他",
   "收盤": 16.05,
   "RS60": "90.0%",
   "RS週": "92.3%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 16.0,
   "停損點": 10.5,
   "平台": "無平台"
  },
  {
   "股票": "2493.TW",
   "名稱": "揚博",
   "產業": "電子零組件",
   "收盤": 177.5,
   "RS60": "89.6%",
   "RS週": "91.3%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 178.0,
   "停損點": 136.0,
   "平台": "無平台"
  },
  {
   "股票": "6907.TWO",
   "名稱": "雅特力-KY",
   "產業": "上櫃",
   "收盤": 169.0,
   "RS60": "87.1%",
   "RS週": "87.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 169.0,
   "停損點": 116.0,
   "平台": "無平台"
  },
  {
   "股票": "3288.TWO",
   "名稱": "點晶",
   "產業": "上櫃",
   "收盤": 24.25,
   "RS60": "87.0%",
   "RS週": "89.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 24.0,
   "停損點": 14.5,
   "平台": "無平台"
  },
  {
   "股票": "3114.TWO",
   "名稱": "好德",
   "產業": "上櫃",
   "收盤": 40.6,
   "RS60": "86.8%",
   "RS週": "87.7%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 40.5,
   "停損點": 28.0,
   "平台": "無平台"
  },
  {
   "股票": "8070.TW",
   "名稱": "長華*",
   "產業": "電子通路",
   "收盤": 65.3,
   "RS60": "85.5%",
   "RS週": "85.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 65.0,
   "停損點": 44.0,
   "平台": "無平台"
  },
  {
   "股票": "5701.TWO",
   "名稱": "劍湖山",
   "產業": "上櫃",
   "收盤": 5.85,
   "RS60": "84.1%",
   "RS週": "87.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 5.75,
   "停損點": 3.25,
   "平台": "無平台"
  },
  {
   "股票": "3066.TWO",
   "名稱": "李洲",
   "產業": "上櫃",
   "收盤": 23.95,
   "RS60": "84.0%",
   "RS週": "78.7%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 24.0,
   "停損點": 20.0,
   "平台": "10日平台突破(振幅5.6%)"
  },
  {
   "股票": "3147.TWO",
   "名稱": "大綜",
   "產業": "上櫃",
   "收盤": 266.5,
   "RS60": "82.4%",
   "RS週": "85.5%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 265.0,
   "停損點": 178.0,
   "平台": "無平台"
  },
  {
   "股票": "5426.TWO",
   "名稱": "振發",
   "產業": "上櫃",
   "收盤": 27.25,
   "RS60": "81.4%",
   "RS週": "81.1%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 27.0,
   "停損點": 18.5,
   "平台": "無平台"
  },
  {
   "股票": "2440.TW",
   "名稱": "太空梭",
   "產業": "電子零組件",
   "收盤": 20.5,
   "RS60": "79.4%",
   "RS週": "82.4%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 20.5,
   "停損點": 16.5,
   "平台": "10日平台突破(振幅10.7%)"
  },
  {
   "股票": "2468.TW",
   "名稱": "華經",
   "產業": "資訊服務",
   "收盤": 44.75,
   "RS60": "77.6%",
   "RS週": "64.3%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 45.0,
   "停損點": 32.5,
   "平台": "無平台"
  },
  {
   "股票": "6585.TW",
   "名稱": "鼎基",
   "產業": "其他",
   "收盤": 109.0,
   "RS60": "76.7%",
   "RS週": "76.0%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 109.0,
   "停損點": 93.0,
   "平台": "10日平台突破(振幅8.1%)"
  },
  {
   "股票": "6890.TW",
   "名稱": "來億-KY",
   "產業": "運動休閒",
   "收盤": 231.5,
   "RS60": "76.2%",
   "RS週": "82.7%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 230.0,
   "停損點": 166.0,
   "平台": "無平台"
  },
  {
   "股票": "3346.TW",
   "名稱": "麗清",
   "產業": "汽車",
   "收盤": 25.55,
   "RS60": "75.7%",
   "RS週": "76.0%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 25.5,
   "停損點": 16.0,
   "平台": "無平台"
  },
  {
   "股票": "1514.TW",
   "名稱": "亞力",
   "產業": "電機機械",
   "收盤": 149.5,
   "RS60": "75.3%",
   "RS週": "75.8%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 150.0,
   "停損點": 118.0,
   "平台": "無平台"
  },
  {
   "股票": "3049.TW",
   "名稱": "精金",
   "產業": "光電",
   "收盤": 17.3,
   "RS60": "75.1%",
   "RS週": "81.3%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 17.5,
   "停損點": 12.0,
   "平台": "無平台"
  },
  {
   "股票": "2483.TW",
   "名稱": "百容",
   "產業": "電子零組件",
   "收盤": 27.7,
   "RS60": "74.8%",
   "RS週": "75.6%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 27.5,
   "停損點": 24.0,
   "平台": "10日平台突破(振幅5.5%)"
  },
  {
   "股票": "1708.TW",
   "名稱": "東鹼",
   "產業": "化學",
   "收盤": 47.65,
   "RS60": "74.3%",
   "RS週": "69.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 47.5,
   "停損點": 36.5,
   "平台": "無平台"
  },
  {
   "股票": "1718.TW",
   "名稱": "中纖",
   "產業": "化學",
   "收盤": 9.68,
   "RS60": "73.2%",
   "RS週": "75.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 9.75,
   "停損點": 6.25,
   "平台": "無平台"
  },
  {
   "股票": "3332.TWO",
   "名稱": "幸康",
   "產業": "上櫃",
   "收盤": 72.6,
   "RS60": "72.6%",
   "RS週": "75.4%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 73.0,
   "停損點": 63.0,
   "平台": "無平台"
  },
  {
   "股票": "1904.TW",
   "名稱": "正隆",
   "產業": "造紙",
   "收盤": 22.3,
   "RS60": "70.9%",
   "RS週": "75.5%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 22.5,
   "停損點": 18.5,
   "平台": "10日平台突破(振幅8.0%)"
  },
  {
   "股票": "3073.TWO",
   "名稱": "天方能源",
   "產業": "上櫃",
   "收盤": 24.8,
   "RS60": "7.2%",
   "RS週": "7.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 25.0,
   "停損點": 19.5,
   "平台": "10日平台突破(振幅11.9%)"
  },
  {
   "股票": "9110.TW",
   "名稱": "越南控-DR",
   "產業": "其他",
   "收盤": 3.96,
   "RS60": "69.8%",
   "RS週": "72.3%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 4.0,
   "停損點": 2.5,
   "平台": "無平台"
  },
  {
   "股票": "1714.TW",
   "名稱": "和桐",
   "產業": "化學",
   "收盤": 12.1,
   "RS60": "69.4%",
   "RS週": "77.1%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 12.0,
   "停損點": 9.25,
   "平台": "無平台"
  },
  {
   "股票": "3015.TW",
   "名稱": "全漢",
   "產業": "電子零組件",
   "收盤": 62.7,
   "RS60": "68.1%",
   "RS週": "70.4%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "追價點": 63.0,
   "停損點": 49.0,
   "平台": "10日平台突破(振幅13.5%)"
  },
  {
   "股票": "6140.TWO",
   "名稱": "訊達",
   "產業": "上櫃",
   "收盤": 25.35,
   "RS60": "67.3%",
   "RS週": "62.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 25.5,
   "停損點": 19.0,
   "平台": "無平台"
  },
  {
   "股票": "4534.TWO",
   "名稱": "慶騰",
   "產業": "上櫃",
   "收盤": 31.65,
   "RS60": "67.2%",
   "RS週": "53.1%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 31.5,
   "停損點": 22.5,
   "平台": "無平台"
  },
  {
   "股票": "6148.TWO",
   "名稱": "驊宏資",
   "產業": "上櫃",
   "收盤": 37.25,
   "RS60": "65.9%",
   "RS週": "46.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 37.0,
   "停損點": 28.0,
   "平台": "無平台"
  },
  {
   "股票": "9934.TW",
   "名稱": "成霖",
   "產業": "居家生活",
   "收盤": 11.25,
   "RS60": "64.5%",
   "RS週": "65.2%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 11.0,
   "停損點": 9.5,
   "平台": "無平台"
  },
  {
   "股票": "1905.TW",
   "名稱": "華紙",
   "產業": "造紙",
   "收盤": 14.0,
   "RS60": "63.8%",
   "RS週": "69.9%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 14.0,
   "停損點": 11.5,
   "平台": "10日平台突破(振幅7.6%)"
  },
  {
   "股票": "8936.TWO",
   "名稱": "國統",
   "產業": "上櫃",
   "收盤": 60.1,
   "RS60": "63.7%",
   "RS週": "59.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 60.0,
   "停損點": 49.0,
   "平台": "10日平台突破(振幅9.4%)"
  },
  {
   "股票": "1611.TW",
   "名稱": "中電",
   "產業": "電器電纜",
   "收盤": 15.0,
   "RS60": "62.6%",
   "RS週": "61.1%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 15.0,
   "停損點": 11.5,
   "平台": "無平台"
  },
  {
   "股票": "3043.TW",
   "名稱": "科風",
   "產業": "其他電子",
   "收盤": 24.2,
   "RS60": "62.2%",
   "RS週": "61.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 24.0,
   "停損點": 20.5,
   "平台": "無平台"
  },
  {
   "股票": "9103.TW",
   "名稱": "美德醫療-DR",
   "產業": "其他",
   "收盤": 5.98,
   "RS60": "61.6%",
   "RS週": "64.9%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "追價點": 6.0,
   "停損點": 5.0,
   "平台": "10日平台突破(振幅11.0%)"
  },
  {
   "股票": "1805.TW",
   "名稱": "寶徠",
   "產業": "建材營造",
   "收盤": 12.1,
   "RS60": "61.6%",
   "RS週": "65.9%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 12.0,
   "停損點": 9.75,
   "平台": "無平台"
  },
  {
   "股票": "6124.TWO",
   "名稱": "業強",
   "產業": "上櫃",
   "收盤": 36.95,
   "RS60": "61.5%",
   "RS週": "57.3%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 37.0,
   "停損點": 29.0,
   "平台": "無平台"
  },
  {
   "股票": "8201.TW",
   "名稱": "無敵",
   "產業": "其他電子",
   "收盤": 15.05,
   "RS60": "60.2%",
   "RS週": "57.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 15.0,
   "停損點": 12.5,
   "平台": "10日平台突破(振幅6.5%)"
  },
  {
   "股票": "3027.TW",
   "名稱": "盛達",
   "產業": "通信網路",
   "收盤": 24.25,
   "RS60": "57.2%",
   "RS週": "61.7%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 24.0,
   "停損點": 17.5,
   "平台": "無平台"
  },
  {
   "股票": "911608.TW",
   "名稱": "明輝-DR",
   "產業": "其他",
   "收盤": 3.22,
   "RS60": "49.2%",
   "RS週": "51.0%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 3.25,
   "停損點": 2.5,
   "平台": "10日平台突破(振幅11.4%)"
  },
  {
   "股票": "5202.TWO",
   "名稱": "力新",
   "產業": "上櫃",
   "收盤": 14.75,
   "RS60": "47.1%",
   "RS週": "36.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 15.0,
   "停損點": 11.5,
   "平台": "無平台"
  },
  {
   "股票": "3308.TW",
   "名稱": "聯德",
   "產業": "電子零組件",
   "收盤": 23.95,
   "RS60": "46.7%",
   "RS週": "52.1%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 24.0,
   "停損點": 19.5,
   "平台": "10日平台突破(振幅9.0%)"
  },
  {
   "股票": "4426.TW",
   "名稱": "利勤",
   "產業": "紡織纖維",
   "收盤": 9.4,
   "RS60": "42.8%",
   "RS週": "46.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 9.5,
   "停損點": 7.5,
   "平台": "無平台"
  },
  {
   "股票": "1515.TW",
   "名稱": "力山",
   "產業": "電機機械",
   "收盤": 25.3,
   "RS60": "41.3%",
   "RS週": "42.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 25.5,
   "停損點": 21.0,
   "平台": "無平台"
  },
  {
   "股票": "3284.TWO",
   "名稱": "太普高",
   "產業": "上櫃",
   "收盤": 19.1,
   "RS60": "40.8%",
   "RS週": "32.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 19.0,
   "停損點": 15.5,
   "平台": "10日平台突破(振幅9.8%)"
  },
  {
   "股票": "911622.TW",
   "名稱": "泰聚亨-DR",
   "產業": "其他",
   "收盤": 4.1,
   "RS60": "39.2%",
   "RS週": "45.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 4.0,
   "停損點": 3.5,
   "平台": "10日平台突破(振幅6.0%)"
  },
  {
   "股票": "1906.TW",
   "名稱": "寶隆",
   "產業": "造紙",
   "收盤": 11.45,
   "RS60": "37.6%",
   "RS週": "42.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 11.5,
   "停損點": 9.75,
   "平台": "10日平台突破(振幅6.5%)"
  },
  {
   "股票": "8085.TWO",
   "名稱": "福華",
   "產業": "上櫃",
   "收盤": 16.1,
   "RS60": "33.7%",
   "RS週": "16.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 16.0,
   "停損點": 11.0,
   "平台": "無平台"
  },
  {
   "股票": "2072.TW",
   "名稱": "世紀風電",
   "產業": "綠能環保",
   "收盤": 199.0,
   "RS60": "3.8%",
   "RS週": "2.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 199.0,
   "停損點": 162.0,
   "平台": "10日平台突破(振幅9.4%)"
  },
  {
   "股票": "7794.TWO",
   "名稱": "宏碁智新",
   "產業": "上櫃",
   "收盤": 34.9,
   "RS60": "3.0%",
   "RS週": "2.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 35.0,
   "停損點": 28.0,
   "平台": "無平台"
  },
  {
   "股票": "9958.TW",
   "名稱": "世紀鋼",
   "產業": "鋼鐵",
   "收盤": 117.5,
   "RS60": "22.2%",
   "RS週": "17.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "追價點": 118.0,
   "停損點": 99.0,
   "平台": "10日平台突破(振幅5.4%)"
  }
 ],
 "強勢創新高": [
  {
   "股票": "1809.TW",
   "名稱": "中釉",
   "產業": "玻璃陶瓷",
   "收盤": 58.5,
   "RS60": "98.1%",
   "RS週": "97.7%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "4807.TW",
   "名稱": "日成-KY",
   "產業": "貿易百貨",
   "收盤": 35.35,
   "RS60": "95.9%",
   "RS週": "97.1%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "4931.TWO",
   "名稱": "新盛力",
   "產業": "上櫃",
   "收盤": 260.0,
   "RS60": "95.5%",
   "RS週": "92.8%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3615.TWO",
   "名稱": "安可",
   "產業": "上櫃",
   "收盤": 57.9,
   "RS60": "93.2%",
   "RS週": "87.7%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2855.TW",
   "名稱": "統一證",
   "產業": "金融保險",
   "收盤": 55.5,
   "RS60": "92.3%",
   "RS週": "93.8%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2409.TW",
   "名稱": "友達",
   "產業": "光電",
   "收盤": 29.25,
   "RS60": "92.0%",
   "RS週": "92.7%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6265.TWO",
   "名稱": "方土昶",
   "產業": "上櫃",
   "收盤": 63.9,
   "RS60": "91.8%",
   "RS週": "88.8%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6465.TWO",
   "名稱": "威潤",
   "產業": "上櫃",
   "收盤": 58.0,
   "RS60": "90.7%",
   "RS週": "92.9%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3406.TW",
   "名稱": "玉晶光",
   "產業": "光電",
   "收盤": 659.0,
   "RS60": "86.4%",
   "RS週": "87.1%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3057.TW",
   "名稱": "喬鼎",
   "產業": "電腦周邊",
   "收盤": 23.55,
   "RS60": "85.8%",
   "RS週": "88.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6282.TW",
   "名稱": "康舒",
   "產業": "電子零組件",
   "收盤": 70.8,
   "RS60": "85.2%",
   "RS週": "87.2%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6485.TWO",
   "名稱": "點序",
   "產業": "上櫃",
   "收盤": 124.0,
   "RS60": "84.9%",
   "RS週": "83.9%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3054.TW",
   "名稱": "立萬利",
   "產業": "食品",
   "收盤": 83.6,
   "RS60": "84.5%",
   "RS週": "63.9%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "5210.TWO",
   "名稱": "寶碩",
   "產業": "上櫃",
   "收盤": 31.3,
   "RS60": "81.7%",
   "RS週": "86.0%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "5353.TWO",
   "名稱": "台林",
   "產業": "上櫃",
   "收盤": 33.5,
   "RS60": "80.8%",
   "RS週": "80.2%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3511.TWO",
   "名稱": "矽瑪",
   "產業": "上櫃",
   "收盤": 27.0,
   "RS60": "80.5%",
   "RS週": "81.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "8088.TWO",
   "名稱": "品安",
   "產業": "上櫃",
   "收盤": 67.6,
   "RS60": "79.7%",
   "RS週": "68.9%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2883.TW",
   "名稱": "凱基金",
   "產業": "金融保險",
   "收盤": 27.4,
   "RS60": "77.6%",
   "RS週": "80.0%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2390.TW",
   "名稱": "云辰",
   "產業": "其他電子",
   "收盤": 13.1,
   "RS60": "76.6%",
   "RS週": "79.0%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "8277.TWO",
   "名稱": "商丞",
   "產業": "上櫃",
   "收盤": 12.0,
   "RS60": "75.1%",
   "RS週": "83.7%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2364.TW",
   "名稱": "倫飛",
   "產業": "電腦周邊",
   "收盤": 80.6,
   "RS60": "74.2%",
   "RS週": "74.9%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6126.TWO",
   "名稱": "信音",
   "產業": "上櫃",
   "收盤": 43.0,
   "RS60": "73.0%",
   "RS週": "77.8%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2414.TW",
   "名稱": "精技",
   "產業": "電子通路",
   "收盤": 53.3,
   "RS60": "73.0%",
   "RS週": "68.6%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "8077.TWO",
   "名稱": "洛碁",
   "產業": "上櫃",
   "收盤": 54.2,
   "RS60": "71.5%",
   "RS週": "73.0%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2108.TW",
   "名稱": "南帝",
   "產業": "橡膠",
   "收盤": 30.9,
   "RS60": "70.6%",
   "RS週": "67.9%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1723.TW",
   "名稱": "中碳",
   "產業": "化學",
   "收盤": 86.5,
   "RS60": "70.0%",
   "RS週": "61.8%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "8076.TWO",
   "名稱": "伍豐",
   "產業": "上櫃",
   "收盤": 28.6,
   "RS60": "68.9%",
   "RS週": "61.3%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1504.TW",
   "名稱": "東元",
   "產業": "電機機械",
   "收盤": 87.0,
   "RS60": "68.7%",
   "RS週": "71.6%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "1513.TW",
   "名稱": "中興電",
   "產業": "電機機械",
   "收盤": 187.0,
   "RS60": "68.2%",
   "RS週": "66.5%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "1709.TW",
   "名稱": "和益",
   "產業": "化學",
   "收盤": 20.7,
   "RS60": "67.4%",
   "RS週": "69.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3628.TWO",
   "名稱": "盈正",
   "產業": "上櫃",
   "收盤": 77.5,
   "RS60": "66.5%",
   "RS週": "65.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1612.TW",
   "名稱": "宏泰",
   "產業": "電器電纜",
   "收盤": 40.65,
   "RS60": "65.9%",
   "RS週": "67.5%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6982.TWO",
   "名稱": "大井泵浦",
   "產業": "上櫃",
   "收盤": 63.2,
   "RS60": "65.8%",
   "RS週": "69.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "4771.TW",
   "名稱": "望隼",
   "產業": "生技醫療",
   "收盤": 207.0,
   "RS60": "65.1%",
   "RS週": "66.3%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "6569.TWO",
   "名稱": "醫揚",
   "產業": "上櫃",
   "收盤": 111.5,
   "RS60": "63.6%",
   "RS週": "63.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1609.TW",
   "名稱": "大亞",
   "產業": "電器電纜",
   "收盤": 43.0,
   "RS60": "63.6%",
   "RS週": "68.0%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "3617.TW",
   "名稱": "碩天",
   "產業": "其他電子",
   "收盤": 221.5,
   "RS60": "63.5%",
   "RS週": "71.6%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2457.TW",
   "名稱": "飛宏",
   "產業": "電子零組件",
   "收盤": 32.05,
   "RS60": "62.7%",
   "RS週": "65.1%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2887.TW",
   "名稱": "台新新光金",
   "產業": "金融保險",
   "收盤": 28.55,
   "RS60": "62.7%",
   "RS週": "63.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "4147.TWO",
   "名稱": "中裕",
   "產業": "上櫃",
   "收盤": 58.6,
   "RS60": "61.9%",
   "RS週": "64.0%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2031.TW",
   "名稱": "新光鋼",
   "產業": "鋼鐵",
   "收盤": 43.0,
   "RS60": "61.0%",
   "RS週": "56.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2834.TW",
   "名稱": "臺企銀",
   "產業": "金融保險",
   "收盤": 17.1,
   "RS60": "58.6%",
   "RS週": "62.0%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2912.TW",
   "名稱": "統一超",
   "產業": "貿易百貨",
   "收盤": 246.0,
   "RS60": "58.1%",
   "RS週": "60.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "9917.TW",
   "名稱": "中保科",
   "產業": "其他",
   "收盤": 117.0,
   "RS60": "56.8%",
   "RS週": "46.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1446.TW",
   "名稱": "宏和",
   "產業": "紡織纖維",
   "收盤": 16.75,
   "RS60": "56.6%",
   "RS週": "43.1%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "6123.TWO",
   "名稱": "上奇",
   "產業": "上櫃",
   "收盤": 47.3,
   "RS60": "56.2%",
   "RS週": "54.7%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3058.TW",
   "名稱": "立德",
   "產業": "電子零組件",
   "收盤": 10.5,
   "RS60": "56.0%",
   "RS週": "62.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "5530.TWO",
   "名稱": "龍巖",
   "產業": "上櫃",
   "收盤": 54.8,
   "RS60": "54.8%",
   "RS週": "60.9%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "1460.TW",
   "名稱": "宏遠",
   "產業": "紡織纖維",
   "收盤": 7.53,
   "RS60": "54.7%",
   "RS週": "57.7%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "6170.TWO",
   "名稱": "統振",
   "產業": "上櫃",
   "收盤": 53.1,
   "RS60": "54.6%",
   "RS週": "48.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2880.TW",
   "名稱": "華南金",
   "產業": "金融保險",
   "收盤": 37.7,
   "RS60": "54.4%",
   "RS週": "58.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "2849.TW",
   "名稱": "安泰銀",
   "產業": "金融保險",
   "收盤": 14.2,
   "RS60": "52.9%",
   "RS週": "56.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1338.TW",
   "名稱": "廣華-KY",
   "產業": "汽車",
   "收盤": 17.1,
   "RS60": "52.5%",
   "RS週": "60.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1808.TW",
   "名稱": "潤隆",
   "產業": "建材營造",
   "收盤": 31.7,
   "RS60": "52.3%",
   "RS週": "40.5%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1909.TW",
   "名稱": "榮成",
   "產業": "造紙",
   "收盤": 9.93,
   "RS60": "52.1%",
   "RS週": "53.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "1907.TW",
   "名稱": "永豐餘",
   "產業": "造紙",
   "收盤": 26.4,
   "RS60": "51.6%",
   "RS週": "57.5%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "6115.TW",
   "名稱": "鎰勝",
   "產業": "電子零組件",
   "收盤": 49.9,
   "RS60": "50.4%",
   "RS週": "52.7%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "5706.TW",
   "名稱": "鳳凰",
   "產業": "觀光餐旅",
   "收盤": 53.5,
   "RS60": "49.8%",
   "RS週": "48.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "1342.TW",
   "名稱": "八貫",
   "產業": "其他",
   "收盤": 100.5,
   "RS60": "48.0%",
   "RS週": "60.7%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "5508.TWO",
   "名稱": "永信建",
   "產業": "上櫃",
   "收盤": 54.6,
   "RS60": "46.1%",
   "RS週": "41.9%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1726.TW",
   "名稱": "永記",
   "產業": "化學",
   "收盤": 79.2,
   "RS60": "46.0%",
   "RS週": "49.6%",
   "均線慣性": "10MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3716.TW",
   "名稱": "中化控股",
   "產業": "生技醫療",
   "收盤": 35.4,
   "RS60": "46.0%",
   "RS週": "50.4%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2801.TW",
   "名稱": "彰銀",
   "產業": "金融保險",
   "收盤": 21.4,
   "RS60": "45.9%",
   "RS週": "46.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "3622.TW",
   "名稱": "洋華",
   "產業": "光電",
   "收盤": 61.3,
   "RS60": "45.7%",
   "RS週": "43.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1535.TW",
   "名稱": "中宇",
   "產業": "電機機械",
   "收盤": 52.4,
   "RS60": "45.6%",
   "RS週": "30.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "初段"
  },
  {
   "股票": "1537.TW",
   "名稱": "廣隆",
   "產業": "電機機械",
   "收盤": 128.5,
   "RS60": "45.4%",
   "RS週": "44.9%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "1416.TW",
   "名稱": "廣豐",
   "產業": "其他",
   "收盤": 11.8,
   "RS60": "43.3%",
   "RS週": "40.1%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "8341.TW",
   "名稱": "日友",
   "產業": "綠能環保",
   "收盤": 78.6,
   "RS60": "42.7%",
   "RS週": "44.2%",
   "均線慣性": "20MA慣性",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "5880.TW",
   "名稱": "合庫金",
   "產業": "金融保險",
   "收盤": 23.7,
   "RS60": "41.8%",
   "RS週": "45.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "1307.TW",
   "名稱": "三芳",
   "產業": "塑膠",
   "收盤": 34.45,
   "RS60": "40.7%",
   "RS週": "45.8%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "2845.TW",
   "名稱": "遠東銀",
   "產業": "金融保險",
   "收盤": 12.55,
   "RS60": "40.5%",
   "RS週": "42.2%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "中段"
  },
  {
   "股票": "8432.TWO",
   "名稱": "東生華",
   "產業": "上櫃",
   "收盤": 52.0,
   "RS60": "40.4%",
   "RS週": "40.6%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  },
  {
   "股票": "4137.TW",
   "名稱": "麗豐-KY",
   "產業": "生技醫療",
   "收盤": 111.5,
   "RS60": "40.3%",
   "RS週": "47.4%",
   "均線慣性": "慣性偏弱",
   "買賣訊號": "買訊",
   "波段位置": "末段"
  }
 ],
 "均線提醒": []
};
let RPT=null, rptTab='市場總覽', rptLoaded=false;
const RTABS=['市場總覽','持股現況','今日精選','早期族群','明日操作'];
const rg=(o,k,d='−')=>(o&&o[k]!=null&&o[k]!=='')?o[k]:d;
function rsig(s){
  s=String(s||'');
  if(s.includes('買')) return `<span class="tg tg-buy">${s}</span>`;
  if(s.includes('賣')) return `<span class="tg tg-sell">${s}</span>`;
  if(s.includes('持有')) return `<span class="tg tg-hold">${s}</span>`;
  if(s.includes('待')) return `<span class="tg tg-warn">${s}</span>`;
  return s==='−'?'':`<span class="tg tg-go">${s}</span>`;
}

// ===== 大盤分頁（完全獨立於戰報：自己的資料 MKT、自己的 localStorage、自己的雲端 market-save/load）=====
const MKT_KEY='donG_mkt';
let MKT=null, mktLoaded=false;
const EMBEDDED_MKT={"日期":"2026-06-07","產出時間":"2026-06-07 15:27","收盤":45070.94,"漲跌":-606.52,"漲跌幅":-1.33,"波段方向":"偏多","波段分數":100,"信心":"強","短線時機":"轉弱","短線註記":["下跌 -1.33%","向下跳空","KD 高檔死叉","RSI 頂背離","高檔短線轉弱"],"操作基調":"波段方向偏多不變，但短線轉弱、拉回中 → 今天別追高，等回穩或回檔到 MA10／MA20 找買點；跌破季線才轉保守。","波段溫度":{"分數":97,"等級":"過熱","組成":{"距年線分位":99,"帶寬分位":99,"60日乖離分位":90}},"短線溫度":{"分數":66,"等級":"偏熱","組成":{"RSI":71,"K":76,"10日乖離分位":45,"區間位置":78}},"組合判讀":"波段熱 + 短線過熱轉弱 → 漲多回檔(非出場)：今天別追高，等拉回 MA10／MA20 找買點；趨勢未破前不空。","降溫路徑":"未明顯下跌","止穩":"—","趨勢":{"週":"多頭","日":"盤整","60分":"盤整","突破訊號":"⬜觀望"},"均線":{"MA5":45621,"MA10":44790,"MA20":43031,"季線":38316,"半年線":34582,"年線":29806,"排列":"多頭排列","帶寬":"發散(分位99%) ← 趨勢明確/延伸"},"長線乖離":{"距年線":51.2,"分位":99},"量價":"量價中性","OBV":"上升","量能":{"位階":"正常(1.0倍)","判讀":"—","量價背離":"無","今量對20日均量":1.0,"量分位":50},"乖離":{"10日":0.63,"20日":4.74,"60日":12.5,"10日分位":45,"20日分位":70,"60日分位":88,"警示":"正常"},"指標":{"KD":"76/83","KD狀態":"中性・死亡交叉","RSI":71,"MACD":"多方・柱狀轉弱","背離":{"MACD":"無","RSI":"頂背離","OBV":"無"}},"結構":{"區間位置":78,"創60日新高":false,"創60日新低":false,"缺口":"向下跳空"},"K線":"無明顯型態","關鍵價位":{"壓力":[45621,46459],"支撐":[44790,43031,40021],"轉多關卡":45621,"轉空關卡":38316,"短線轉強":45350,"短線轉弱":44950},"極值偵測":"🔺 噴出末端警戒：結構極熱 + 出現轉弱/出貨/背離 → 慎防急速回檔（趨勢未破前不空，但別追、減碼控管）","警示":["短線轉弱：下跌 -1.33%、向下跳空、KD 高檔死叉、RSI 頂背離、高檔短線轉弱 → 今天不宜追高","結構過熱(波段溫度97) + 短線轉弱 → 回檔風險升高，別追高、控管倉位","RSI 頂背離 → 漲勢動能轉弱，留意反轉"]};

function biasColor(d){ return d==='偏多'?'#ff453a': d==='偏空'?'#30d158':'#8e8e93'; }  // 台股：偏多=紅、偏空=綠
function tempColor(b){ return b==='過熱'?'#ff453a': b==='偏熱'?'#ff9f0a': b==='中性'?'#8e8e93': b==='偏冷'?'#5ac8fa':'#0a84ff'; }
function shortColor(d){ return d==='轉強'?'#ff453a': d==='轉弱'?'#30d158':'#8e8e93'; }  // 台股：轉強=紅、轉弱=綠

async function loadMarket(){
  mktLoaded=true;
  const m=document.getElementById('mktMain');
  m.innerHTML='<div class="loading">載入今日大盤中…</div>';
  try{
    const r=await fetch('/api/market-load',{signal:AbortSignal.timeout(20000)});
    const j=await r.json();
    if(j && j.market){
      MKT=JSON.parse(j.market); MKT.__src='cloud';
      try{ localStorage.setItem(MKT_KEY, j.market); }catch(e){}
      renderMkt(); return;
    }
  }catch(e){}
  try{
    const saved=localStorage.getItem(MKT_KEY);
    if(saved){ MKT=JSON.parse(saved); MKT.__src='paste'; }
    else { MKT=EMBEDDED_MKT; MKT.__src='preview'; }
  }catch(e){ MKT=EMBEDDED_MKT; MKT.__src='preview'; }
  renderMkt();
}
function toggleImportMkt(){
  const p=document.getElementById('impPanelMkt');
  if(p) p.style.display=(p.style.display==='none'||!p.style.display)?'block':'none';
}
function doImportMkt(){
  const box=document.getElementById('impBoxMkt');
  const t=(box.value||'').trim();
  if(!t){ alert('請先貼上「大盤分析」複製來的內容'); return; }
  let obj;
  try{ obj=JSON.parse(t); }catch(e){ alert('格式不對，請回大盤分析重新按「複製今日大盤」再貼一次'); return; }
  if(!obj['波段方向'] && !obj['波段溫度'] && !obj['溫度']){ alert('這份看起來不是大盤資料（少了溫度／波段方向）。請確認是按「複製今日大盤」複製來的，而不是每日戰報。'); return; }
  const str=JSON.stringify(obj);
  try{ localStorage.setItem(MKT_KEY, str); }catch(e){}
  MKT=obj; MKT.__src='paste';
  renderMkt();
  fetch('/api/market-save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({market:str})})
    .then(r=>r.json())
    .then(j=>{
      if(j && j.ok){ MKT.__src='cloud'; if(document.getElementById('mktMain').style.display!=='none') renderMkt(); }
      else { alert('已匯入，但雲端同步失敗，手機可能看不到'); }
    })
    .catch(e=>{ alert('已匯入，但雲端同步失敗，手機可能看不到'); });
}

function toggleTempHelp(){
  const p=document.getElementById('tempHelp');
  if(p) p.style.display=(p.style.display==='none'||!p.style.display)?'block':'none';
}
function renderMkt(){
  const m=document.getElementById('mktMain');
  if(!MKT){ loadMarket(); return; }
  const src=MKT.__src;
  const swT=MKT['波段溫度']||{}, shT=MKT['短線溫度']||{}, legacy=MKT['溫度']||null;
  const hasDual=(MKT['波段溫度']!=null || MKT['短線溫度']!=null);
  const swSc=Number(rg(swT,'分數', legacy?rg(legacy,'分數',0):0))||0, swBd=rg(swT,'等級', legacy?rg(legacy,'等級','—'):'—');
  const shSc=Number(rg(shT,'分數',0))||0, shBd=rg(shT,'等級','—');
  const combo=rg(MKT,'組合判讀', legacy?rg(legacy,'操作含義',''):'');
  const dpath=rg(MKT,'降溫路徑', legacy?rg(legacy,'降溫路徑','—'):'—'), stab=rg(MKT,'止穩', legacy?rg(legacy,'止穩','—'):'—');
  const wd=rg(MKT,'波段方向','—'), sd=rg(MKT,'短線時機','—');
  const tr=MKT['趨勢']||{}, ma=MKT['均線']||{}, ind=MKT['指標']||{}, ya=MKT['長線乖離']||{}, kp=MKT['關鍵價位']||{}, bx=MKT['乖離']||{}, vol=MKT['量能']||{};
  const chg=Number(rg(MKT,'漲跌',0))||0;
  const tbar=(label,sc,bd,sub)=>`<div style="margin:12px 6px 2px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px">
        <span style="color:#9fb6cc;font-size:13px">🌡 ${label}${sub?`<span style="color:#62788f;font-size:11px">　${sub}</span>`:''}</span>
        <span><b style="font-size:20px;color:${tempColor(bd)}">${sc}</b><span style="color:#62788f;font-size:12px">/100　${bd}</span></span>
      </div>
      <div style="background:#16273b;border-radius:6px;height:11px;overflow:hidden">
        <div style="width:${Math.max(0,Math.min(100,sc))}%;height:100%;background:${tempColor(bd)}"></div>
      </div>
    </div>`;
  let h=`<div class="imp-bar">
    <button class="imp-btn" onclick="toggleImportMkt()">📋 貼上今日大盤（從大盤分析複製來）</button>
    <div class="imp-panel" id="impPanelMkt" style="display:none">
      <textarea class="imp-box" id="impBoxMkt" placeholder="把「大盤分析」那顆「複製今日大盤」複製到的內容，貼在這裡"></textarea>
      <button class="imp-do" onclick="doImportMkt()">匯入</button>
    </div>
  </div>`;
  h+=`<div class="rpt-date">資料日期：${rg(MKT,'日期')}　產出 ${rg(MKT,'產出時間','')}</div>`;
  h+= src==='cloud' ? `<div class="rpt-src live">● 已同步雲端（手機／電腦都看得到）</div>`
     : src==='paste' ? `<div class="rpt-src live">● 已匯入今日大盤</div>`
     : `<div class="rpt-src cache">● 內建預覽資料（貼上今日大盤後即更新）</div>`;
  h+=`<div class="ov">
    <div class="ov-bias" style="color:${biasColor(wd)}">波段 ${wd}</div>
    <div style="text-align:center;color:#9fb6cc;font-size:14px;margin-top:-4px">
      加權指數 <b style="color:#fff">${rg(MKT,'收盤')}</b>
      <span style="color:${chg>=0?'#ff453a':'#30d158'}">${chg>=0?'▲':'▼'}${Math.abs(chg)} (${rg(MKT,'漲跌幅')}%)</span>
    </div>`;
  if(hasDual){
    h+=tbar('波段溫度',swSc,swBd,'中長線結構');
    h+=tbar('短線溫度',shSc,shBd,'今日過熱/拉回');
  } else {
    h+=tbar('大盤溫度',swSc,swBd,'');
  }
  if(combo) h+=`<div style="color:#cfe0f0;font-size:13px;margin:10px 6px 2px;line-height:1.55">組合判讀：${combo}</div>`;
  const _ex=rg(MKT,'極值偵測','');
  if(_ex){ const _up=_ex.indexOf('🔺')>=0; h+=`<div style="margin:8px 6px 2px;padding:9px 11px;border-radius:8px;font-size:13px;line-height:1.5;background:${_up?'#3a1d1d':'#10283f'};border:1px solid ${_up?'#7a2e2e':'#2e5a7a'};color:${_up?'#ff9f9f':'#9fd2ff'}">${_ex}</div>`; }
  if(dpath!=='—' && dpath!=='未明顯下跌'){
    h+=`<div style="color:#9fb6cc;font-size:12px;margin:2px 6px 0">降溫路徑：${dpath}／止穩：${stab}</div>`;
  }
  h+=`<button onclick="toggleTempHelp()" style="margin:10px 6px 0;background:#16273b;color:#9fb6cc;border:1px solid #1e3a5f;border-radius:8px;padding:6px 12px;font-size:12px;cursor:pointer">🌡 溫度怎麼看？（點開說明）</button>
    <div id="tempHelp" style="display:none;margin:8px 6px 0;background:#0f1d2e;border:1px solid #1e3a5f;border-radius:8px;padding:11px;font-size:12px;color:#cfe0f0;line-height:1.75">
      <div style="color:#ffd479;margin-bottom:7px">關鍵：溫度是「位階（有多熱）」，不是「方向」。要不要動，要配下面的「短線時機（轉強/轉弱）」一起看 —— 例如短線偏熱 + 轉弱 = 拉回。</div>
      <div style="color:#7fd1ff;margin:6px 0 2px"><b>🌡 波段溫度（慢・中長線結構）</b></div>
      80–100 過熱：別追高、控倉，但趨勢仍可能漲（高≠賣）<br>
      60–80 偏熱：多頭健康延伸，正常持有<br>
      40–60 中性：看波段方向操作<br>
      20–40 偏冷：結構打底中<br>
      0–20 過冷：中長線相對低風險區（等方向轉，不是一冷就買）
      <div style="color:#7fd1ff;margin:9px 0 2px"><b>🌡 短線溫度（快・今日）</b></div>
      80–100 過熱：隨時可能拉回，別追高<br>
      60–80 偏熱：一轉弱就是拉回訊號<br>
      40–60 中性：短線正常<br>
      20–40 偏冷：拉回到位（波段多→找買點）<br>
      0–20 過冷：急跌止穩→可短打搶反彈；緩跌→不搶
      <div style="color:#62788f;margin-top:8px;font-size:11px">溫度擅長標極端、給背景、提醒紀律；不擅長抓精確高低點。當風險溫度計用，不當買賣開關。</div>
    </div>`;
  h+=`</div>`;
  h+=`<div class="card">
    <div class="card-meta"><span>波段方向 <b style="color:${biasColor(wd)}">${wd}</b>（分 ${rg(MKT,'波段分數')}／信心 ${rg(MKT,'信心')}）</span></div>
    <div class="card-meta"><span>短線時機 <b style="color:${shortColor(sd)}">${sd}</b></span></div>
    <div class="card-meta" style="color:#cfe0f0;line-height:1.6">操作基調：${rg(MKT,'操作基調','')}</div>
  </div>`;
  h+=`<div class="card">
    <div class="card-meta"><span>趨勢　週<b>${rg(tr,'週')}</b>　日<b>${rg(tr,'日')}</b>　60分<b>${rg(tr,'60分')}</b></span></div>
    <div class="card-meta"><span>日線突破 <b>${rg(tr,'突破訊號')}</b></span></div>
    <div class="card-meta"><span>均線排列 <b>${rg(ma,'排列')}</b></span></div>
    <div class="card-meta"><span>MA5 <b>${rg(ma,'MA5')}</b>／MA10 <b>${rg(ma,'MA10')}</b>／MA20 <b>${rg(ma,'MA20')}</b>／季線 <b>${rg(ma,'季線')}</b>／年線 <b>${rg(ma,'年線')}</b></span></div>
    <div class="card-meta"><span>帶寬 <b>${rg(ma,'帶寬')}</b></span></div>
    <div class="card-meta"><span>長線 距年線 <b>${rg(ya,'距年線')}%</b>（分位${rg(ya,'分位')}%）</span></div>
  </div>`;
  h+=`<div class="card">
    <div class="card-meta" style="color:#ffd479">量能</div>
    <div class="card-meta"><span>位階 <b>${rg(vol,'位階','—')}</b>　量價 <b>${rg(MKT,'量價','—')}</b>　OBV <b>${rg(MKT,'OBV','—')}</b></span></div>`;
  if(rg(vol,'判讀','—')!=='—') h+=`<div class="card-meta"><span style="color:#cfe0f0">${rg(vol,'判讀')}</span></div>`;
  if(rg(vol,'量價背離','無')!=='無' && rg(vol,'量價背離','無')!=='無量資料') h+=`<div class="card-meta"><span style="color:#cfe0f0">量價背離：${rg(vol,'量價背離')}</span></div>`;
  h+=`</div>`;
  h+=`<div class="card">
    <div class="card-meta"><span>KD <b>${rg(ind,'KD')}</b>（${rg(ind,'KD狀態')}）　RSI <b>${rg(ind,'RSI')}</b>　MACD <b>${rg(ind,'MACD')}</b></span></div>
    <div class="card-meta"><span>乖離 10日 <b>${rg(bx,'10日')}%</b>(分位${rg(bx,'10日分位', rg(bx,'分位'))}%)　20日 <b>${rg(bx,'20日')}%</b>(分位${rg(bx,'20日分位','−')}%)　60日 <b>${rg(bx,'60日','−')}%</b>(分位${rg(bx,'60日分位','−')}%)</span></div>
    <div class="card-meta"><span>→ ${rg(bx,'警示')}</span></div>
  </div>`;
  h+=`<div class="card">
    <div class="card-meta"><span>壓力 <b class="c-sell">${(kp['壓力']||[]).join('、')||'−'}</b></span></div>
    <div class="card-meta"><span>支撐 <b class="c-buy">${(kp['支撐']||[]).join('、')||'−'}</b></span></div>
    <div class="card-meta"><span>波段　站上 <b class="c-buy">${rg(kp,'轉多關卡')}</b> 轉強｜跌破 <b class="c-sell">${rg(kp,'轉空關卡')}</b> 轉弱</span></div>
    <div class="card-meta"><span>短線　站上 <b class="c-buy">${rg(kp,'短線轉強')}</b> 轉強｜跌破 <b class="c-sell">${rg(kp,'短線轉弱')}</b> 轉弱（日內/明日）</span></div>
  </div>`;
  const warns=MKT['警示']||[];
  h+=`<div class="card"><div class="card-meta" style="color:#ffd479">⚠ 警示</div>`;
  h+= warns.length? warns.map(w=>`<div class="card-meta" style="color:#cfe0f0;line-height:1.5">• ${w}</div>`).join('') : '<div class="card-meta">無</div>';
  h+=`</div>`;
  m.innerHTML=h;
}

function selectView(v){
  const track=(v==='track');
  const mkt=(v==='大盤');
  document.querySelectorAll('.bottomnav button').forEach(b=>b.classList.toggle('on', b.dataset.view===v));
  document.getElementById('tabs').style.display     = track?'flex':'none';
  document.getElementById('main').style.display     = track?'block':'none';
  document.getElementById('trackBtns').style.display= track?'flex':'none';
  document.getElementById('rptMain').style.display  = (track||mkt)?'none':'block';
  document.getElementById('mktMain').style.display  = mkt?'block':'none';
  window.scrollTo(0,0);
  if(track){ render(); return; }
  if(mkt){ if(!mktLoaded){ loadMarket(); } else { renderMkt(); } return; }
  rptTab=v;
  if(!rptLoaded){ loadReport(); } else { renderRpt(); }
}

function renderRptTabs(){
  document.getElementById('rptTabs').innerHTML=RTABS.map(t=>
    `<button class="tab${t===rptTab?' active':''}" onclick="rptSw('${t}')">${t}</button>`
  ).join('');
}
function rptSw(t){ rptTab=t; renderRpt(); window.scrollTo(0,0); }

async function loadReport(){
  rptLoaded=true;
  const m=document.getElementById('rptMain');
  m.innerHTML='<div class="loading">載入每日戰報中…</div>';
  // 先試雲端（這樣手機也能讀到電腦貼的）
  try{
    const r=await fetch('/api/report-load',{signal:AbortSignal.timeout(20000)});
    const j=await r.json();
    if(j && j.report){
      RPT=JSON.parse(j.report); RPT.__src='cloud';
      try{ localStorage.setItem(RPT_KEY, j.report); }catch(e){}
      renderRpt(); return;
    }
  }catch(e){}
  // 雲端沒有 → 本機 → 內建預覽
  try{
    const saved=localStorage.getItem(RPT_KEY);
    if(saved){ RPT=JSON.parse(saved); RPT.__src='paste'; }
    else { RPT=EMBEDDED_RPT; RPT.__src='preview'; }
  }catch(e){ RPT=EMBEDDED_RPT; RPT.__src='preview'; }
  renderRpt();
}
function toggleImport(){
  const p=document.getElementById('impPanel');
  if(p) p.style.display = (p.style.display==='none'||!p.style.display)?'block':'none';
}
function doImport(){
  const box=document.getElementById('impBox');
  const t=(box.value||'').trim();
  if(!t){ alert('請先貼上 V25 複製來的內容'); return; }
  let obj;
  try{ obj=JSON.parse(t); }catch(e){ alert('格式不對，請回 V25 重新按「複製今日戰報」再貼一次'); return; }
  const str=JSON.stringify(obj);
  try{ localStorage.setItem(RPT_KEY, str); }catch(e){}
  RPT=obj; RPT.__src='paste';
  rptTab='市場總覽';
  renderRpt();
  // 背景同步到雲端（讓手機也讀得到）
  fetch('/api/report-save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report:str})})
    .then(r=>r.json())
    .then(j=>{
      if(j && j.ok){ RPT.__src='cloud'; if(document.getElementById('rptMain').style.display!=='none') renderRpt(); }
      else { alert('已匯入，但雲端同步失敗，手機可能看不到'); }
    })
    .catch(e=>{ alert('已匯入，但雲端同步失敗，手機可能看不到'); });
}

function renderRpt(){
  const m=document.getElementById('rptMain');
  if(!RPT){ loadReport(); return; }
  const src = RPT.__src;
  let h=`<div class="imp-bar">
    <button class="imp-btn" onclick="toggleImport()">📋 貼上今日戰報（從 V25 複製來）</button>
    <div class="imp-panel" id="impPanel" style="display:none">
      <textarea class="imp-box" id="impBox" placeholder="把 V25 那顆「複製今日戰報」複製到的內容，貼在這裡"></textarea>
      <button class="imp-do" onclick="doImport()">匯入</button>
    </div>
  </div>`;
  h+=`<div class="rpt-date">資料日期：${rg(RPT,'日期')}　產出 ${rg(RPT,'產出時間','')}</div>`;
  h+= src==='cloud' ? `<div class="rpt-src live">● 已同步雲端（手機／電腦都看得到）</div>`
     : src==='paste' ? `<div class="rpt-src live">● 已匯入今日戰報</div>`
     : `<div class="rpt-src cache">● 內建預覽資料（貼上今日戰報後即更新）</div>`;
  if(rptTab==='市場總覽')      h+=rptMarket();
  else if(rptTab==='持股現況') h+=rptHold();
  else if(rptTab==='今日精選') h+=rptPick();
  else if(rptTab==='早期族群') h+=rptEarly();
  else if(rptTab==='明日操作') h+=rptTmr();
  m.innerHTML=h;
  document.querySelectorAll('.rtoggle button').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('.rtoggle button').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.rpane').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');document.getElementById(b.dataset.pane).classList.add('on');
  });
}

function rptMarket(){
  const o=RPT['市場總覽']||{};
  const rise=RPT['起漲股']||[], nh=RPT['強勢創新高']||[];
  let h=`<div class="ov">
    <div class="ov-bias">${rg(o,'市場偏向')}</div>
    <div class="ov-grid">
      <div class="ov-stat"><div class="ov-k">多方族群</div><div class="ov-v c-buy">${rg(o,'多方族群數','0')}</div></div>
      <div class="ov-stat"><div class="ov-k">空方族群</div><div class="ov-v c-sell">${rg(o,'空方族群數','0')}</div></div>
      <div class="ov-stat"><div class="ov-k">起漲股</div><div class="ov-v">${rg(o,'起漲股數','0')}</div></div>
      <div class="ov-stat"><div class="ov-k">強勢創新高</div><div class="ov-v">${rg(o,'強勢創新高','0')}</div></div>
    </div>
    ${(o['早期族群']&&o['早期族群'].length)?`<div class="ov-chips">🌱 ${o['早期族群'].map(x=>`<span class="ov-chip">${x}</span>`).join('')}</div>`:''}
  </div>
  <div class="rtoggle">
    <button class="on" data-pane="pn-rise">起漲股 ${rise.length}</button>
    <button data-pane="pn-nh">強勢創新高 ${nh.length}</button>
  </div>
  <div class="rpane on" id="pn-rise">`;
  h+= rise.length?rise.map(r=>`<div class="card">
      <div class="card-row"><div class="card-stk"><span class="card-nm">${rg(r,'名稱')}</span>
        <span class="card-cd">${rg(r,'股票')}</span>${rsig(rg(r,'買賣訊號'))}</div>
        <span class="card-px">${rg(r,'收盤')}</span></div>
      <div class="card-meta"><span>RS60 <b>${rg(r,'RS60')}</b></span><span>慣性 <b>${rg(r,'均線慣性')}</b></span><span>平台 <b>${rg(r,'平台')}</b></span></div>
      <div class="card-meta"><span>追價 <b class="c-buy">${rg(r,'追價點')}</b></span><span>停損 <b class="c-sell">${rg(r,'停損點')}</b></span></div>
    </div>`).join(''):'<div class="empty">無起漲股</div>';
  h+=`</div><div class="rpane" id="pn-nh">`;
  h+= nh.length?nh.map(r=>`<div class="card">
      <div class="card-row"><div class="card-stk"><span class="card-nm">${rg(r,'名稱')}</span>
        <span class="card-cd">${rg(r,'股票')}</span>${rsig(rg(r,'買賣訊號'))}</div>
        <span class="card-px">${rg(r,'收盤')}</span></div>
      <div class="card-meta"><span>RS60 <b>${rg(r,'RS60')}</b></span><span>慣性 <b>${rg(r,'均線慣性')}</b></span><span>波段位置 <b>${rg(r,'波段位置')}</b></span></div>
    </div>`).join(''):'<div class="empty">無資料</div>';
  h+=`</div>`;
  return h;
}

// ===== V27：持股五段式分析（波段方向/多週期/撐壓/交易計畫/明日觀察）=====
function f5tg(btn){
  const e=btn.parentElement.lastElementChild;
  const open=e.style.display==='none';
  e.style.display=open?'block':'none';
  btn.textContent=open?'▲ 收合五段分析':'▼ 五段分析';
}
function fiveBlock(s){
  const f=s['五段'];
  if(!f||typeof f!=='object') return '';
  const secs=[['一、波段方向','波段方向'],['二、多週期細看','多週期'],['三、撐壓','撐壓'],['四、交易計畫','交易計畫'],['五、明日觀察','明日觀察']];
  const NL=String.fromCharCode(10);
  let inner='';
  for(const it of secs){
    const v=f[it[1]];
    if(!v) continue;
    const body=String(v).split(NL).map(x=>'<div style="margin:2px 0">'+x+'</div>').join('');
    inner+='<div style="margin:8px 0 2px"><div style="color:#38bdf8;font-weight:700;font-size:13px;margin-bottom:3px">◤'+it[0]+'◢</div><div style="color:#cdd9e5;font-size:13px;line-height:1.65">'+body+'</div></div>';
  }
  if(!inner) return '';
  const wkv=String(rg(s,'週線環境','−'));
  let wk='';
  if(wkv!=='−'){
    const col=wkv.includes('強')?'#ff6b6b':(wkv.includes('弱')?'#34c759':'#ffd479');
    wk='<span style="margin-left:8px;color:'+col+';font-size:12px;font-weight:700">週線'+wkv+'</span>';
  }
  return '<div style="margin-top:8px;border-top:1px solid #1e3a5f;padding-top:8px">'
    +'<button onclick="f5tg(this)" style="background:#132338;color:#38bdf8;border:1px solid #1e3a5f;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:700;cursor:pointer">▼ 五段分析</button>'+wk
    +'<div style="display:none">'+inner+'</div></div>';
}

function rptHold(){
  const arr=RPT['持股現況']||[];
  if(!arr.length) return '<div class="empty">無持股資料</div>';
  return arr.map(s=>`<div class="card">
    <div class="card-row"><div class="card-stk"><span class="card-nm">${rg(s,'名稱')}</span>
      <span class="card-cd">${rg(s,'代號')}</span>${rsig(rg(s,'訊號'))}</div>
      <span class="card-px">${rg(s,'現價')}</span></div>
    ${rg(s,'RS60','−')!=='−'?`<div class="card-meta">
      <span>RS20 <b>${rg(s,'RS20')}</b></span>
      <span>RS60 <b>${rg(s,'RS60')}</b></span>
      <span>RS120 <b>${rg(s,'RS120')}</b></span>
      <span>RS週 <b>${rg(s,'RS週')}</b></span>
    </div>`:''}
    <div class="card-meta">
      <span>慣性 <b>${rg(s,'均線慣性')}</b></span>
      ${rg(s,'長期趨勢','−')!=='−'?`<span>長期 <b>${rg(s,'長期趨勢')}</b></span>`:''}
      ${rg(s,'波段位置','−')!=='−'?`<span>波段位置 <b>${rg(s,'波段位置')}</b></span>`:''}
      ${rg(s,'回檔健康','−')!=='−'?`<span>回檔 <b>${rg(s,'回檔健康')}</b></span>`:''}
    </div>
    ${rg(s,'乖離','−')!=='−'?`<div class="card-meta"><span>乖離 <b>${rg(s,'乖離')}</b></span></div>`:''}
    <div class="card-meta">
      <span>支撐 <b>${rg(s,'支撐')}</b></span>
      <span>壓力 <b>${rg(s,'壓力')}</b></span>
      <span>停損 <b class="c-sell">${rg(s,'停損')}</b></span>
      <span>目標 <b class="c-buy">${rg(s,'目標')}</b></span>
    </div>
    ${rg(s,'訊號說明','−')!=='−'?`<div class="card-meta"><span>訊號 <b style="color:#cdd9e5;font-weight:500">${rg(s,'訊號說明')}</b></span></div>`:''}
    ${(rg(s,'假跌破','正常')!=='正常'&&rg(s,'假跌破','−')!=='−')?`<div class="card-meta"><span>假跌破 <b style="color:#ffd479">${rg(s,'假跌破')}</b>　${rg(s,'假跌破說明','')}</span></div>`:''}
    ${rg(s,'波段操作','−')!=='−'?`<div class="card-meta"><span>波段 <b style="color:#cdd9e5;font-weight:500">${rg(s,'波段操作')}</b></span></div>`:''}
    ${rg(s,'均線提醒','−')!=='−'?`<div class="card-meta"><span style="color:#ffd479">⚡ ${rg(s,'均線提醒')}</span></div>`:''}
    <div class="card-meta"><span>明日 <b>${rg(s,'明日預測')}</b>　${rg(s,'明日操作','')}</span></div>
    ${fiveBlock(s)}
  </div>`).join('');
}

function rptPick(){
  const arr=RPT['今日精選']||[];
  if(!arr.length) return '<div class="empty">今日無精選標的</div>';
  return arr.map(s=>`<div class="card">
    <div class="card-row"><div class="card-stk"><span class="card-nm">${rg(s,'名稱')}</span>
      <span class="card-cd">${rg(s,'代號')}</span>
      ${String(rg(s,'類型')).includes('起漲')?`<span class="tg tg-rise">${rg(s,'類型')}</span>`:`<span class="tg tg-go">${rg(s,'類型')}</span>`}
      ${rsig(rg(s,'訊號'))}</div>
      <span class="card-px">${rg(s,'現價')}</span></div>
    <div class="card-meta"><span>RS60 <b>${rg(s,'RS60')}</b></span><span>慣性 <b>${rg(s,'均線慣性')}</b></span></div>
    <div class="card-meta"><span>進場 <b style="color:#38bdf8">${rg(s,'進場條件')}</b></span></div>
    <div class="card-meta"><span>支撐 <b>${rg(s,'支撐')}</b></span><span>停損 <b class="c-sell">${rg(s,'停損')}</b></span><span>壓力 <b>${rg(s,'壓力')}</b></span></div>
    <div class="card-meta"><span>${rg(s,'理由','')}</span></div>
  </div>`).join('');
}

function rptEarly(){
  const arr=RPT['早期族群']||[];
  if(!arr.length) return '<div class="empty">今日無早期族群</div>';
  return arr.map(grp=>`<div class="card">
    <div class="card-row"><span class="card-nm">${rg(grp,'族群')}</span>
      <span class="tg tg-rise">${rg(grp,'階段')}</span></div>
    <div class="card-meta"><span>族群RS60 <b>${rg(grp,'RS60')}</b></span><span>動能加速 <b class="c-buy">+${rg(grp,'動能加速')}</b></span></div>
    ${(grp['精選個股']||[]).map(p=>`<div class="pick">
      <div class="card-row"><div class="card-stk"><span class="card-nm" style="font-size:14px">${rg(p,'名稱')}</span>
        <span class="card-cd">${rg(p,'代號')}</span></div><span class="card-px" style="font-size:15px">${rg(p,'現價')}</span></div>
      <div class="card-meta"><span>進場 <b style="color:#38bdf8">${rg(p,'進場')}</b></span>
        <span>停損 <b class="c-sell">${rg(p,'停損')}</b></span><span>風報比 <b>${rg(p,'風報比')}</b></span>
        <span>評分 <b style="color:#ffd60a">${rg(p,'評分')}</b></span></div>
    </div>`).join('')}
  </div>`).join('');
}

function rptTmr(){
  const arr=RPT['明日操作']||[];
  if(!arr.length) return '<div class="empty">無明日操作</div>';
  return arr.map(s=>{
    const act=String(rg(s,'動作'));
    const cls=act.includes('出場')?'tg-sell':act.includes('續抱')?'tg-buy':act.includes('⭐')?'tg-rise':'tg-hold';
    return `<div class="card">
      <div class="card-row"><div class="card-stk"><span class="card-nm">${rg(s,'名稱')}</span>
        <span class="card-cd">${rg(s,'代號')}</span><span class="tg ${cls}">${act}</span></div></div>
      <div class="card-meta"><span>停損 <b class="c-sell">${rg(s,'停損')}</b></span><span>明日 <b>${rg(s,'明日')}</b></span></div>
    </div>`;
  }).join('');
}

render();
window.addEventListener('load',()=>{ setTimeout(()=>loadCloud(),5000); });
</script>
</body>
</html>"""


@app.route('/')
def home():
    return HTML_PAGE

if __name__ == '__main__':
    app.run()
