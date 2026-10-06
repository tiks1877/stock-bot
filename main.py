import time
from datetime import datetime, timezone
import requests
import yfinance as yf
import pandas as pd
import numpy as np

TELEGRAM_TOKEN = "8829545402:AAFFPm1WGXlIFlicOyzMg97CoptIJ_KiGmg"
TELEGRAM_CHAT_ID = "5267209755"
TECH_GIANTS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "TSLA"]
ALL_TICKERS = TECH_GIANTS + ["QQQ"]

ALERT_COOLDOWN = 600  # 10 分鐘冷卻，避免同標的重複發送
last_alert_time = {}

def is_market_opening_noise():
    """判斷是否處於美股剛開盤前 15 分鐘 (美東時間 09:30 - 09:45)"""
    now_utc = datetime.now(timezone.utc)
    # 美國夏令時間美東為 UTC-4，冬令為 UTC-5
    # 以開盤時間 13:30 UTC (夏令) 或 14:30 UTC (冬令) 之對應區間過濾開盤前 15 分鐘
    minute_of_day = now_utc.hour * 60 + now_utc.minute
    # 夏令 13:30-13:45 (810-825) / 冬令 14:30-14:45 (870-885)
    if (810 <= minute_of_day < 825) or (870 <= minute_of_day < 885):
        return True
    return False

def send_signal(action, ticker, price, sl, tp, reason):
    """發送精準買賣指引，附帶做多/做空明確方向與風控價位"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    if action == "BUY":
        header = "🟢 【建議：買入（做多）】"
        target_hint = "看漲獲利"
    else:
        header = "🔴 【建議：賣出（做空 / 平倉）】"
        target_hint = "看跌獲利或現貨減碼"

    text = (
        f"{header}\n"
        f"標的：{ticker}\n"
        f"現價：${price:.2f}\n"
        f"止損：${sl:.2f}\n"
        f"止盈：${tp:.2f} ({target_hint})\n"
        f"原因：{reason}\n"
        f"時間：{time.strftime('%H:%M:%S')}"
    )
    
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=5)
        print(f"[{time.strftime('%H:%M:%S')}] 成功推播訊號：{ticker} -> {action}")
    except Exception as e:
        print(f"推播失敗: {e}")

def calculate_atr(df, period=14):
    """計算真實波動區間 (ATR)"""
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def run_monitoring_cycle():
    now = time.time()
    
    # 1. 避開開盤前 15 分鐘極端洗盤
    if is_market_opening_noise():
        print(f"[{time.strftime('%H:%M:%S')}] 開盤前 15 分鐘噪音過濾中，暫停發送訊號...")
        return

    try:
        # 2. 批次抓取 1 分鐘線 (大幅降低網路延遲)
        batch_df = yf.download(ALL_TICKERS, period="5d", interval="1m", prepost=True, progress=False, group_by='ticker')
        if batch_df.empty:
            return

        # 3. 獲取 QQQ 大盤即時動態
        qqq_data = batch_df['QQQ'].dropna()
        if len(qqq_data) < 2:
            return
        qqq_latest = qqq_data['Close'].iloc[-1]
        qqq_prev = qqq_data['Close'].iloc[-2]
        qqq_change = ((qqq_latest - qqq_prev) / qqq_prev) * 100

        # 4. 個股量化掃描
        for ticker in TECH_GIANTS:
            if ticker in last_alert_time and (now - last_alert_time[ticker] < ALERT_COOLDOWN):
                continue

            df = batch_df[ticker].dropna()
            if len(df) < 30:
                continue

            latest_close = float(df['Close'].iloc[-1])
            prev_close = float(df['Close'].iloc[-2])
            minute_change = ((latest_close - prev_close) / prev_close) * 100

            # 計算爆量條件 (成交量 > 前 20 根均量 1.8 倍)
            vol_current = float(df['Volume'].iloc[-1])
            vol_sma20 = float(df['Volume'].rolling(20).mean().iloc[-2])
            volume_surge = (vol_sma20 > 0) and (vol_current >= vol_sma20 * 1.8)

            # 計算 RSI
            delta = df['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            # 計算短期 EMA 趨勢 (EMA 50 代表日內主要支撐阻力)
            ema50 = float(df['Close'].ewm(span=50).mean().iloc[-1])
            is_bull = latest_close > ema50
            is_bear = latest_close < ema50

            # 計算 ATR 用於精確停損與停利
            atr = calculate_atr(df, period=14)
            if np.isnan(atr) or atr == 0:
                atr = latest_close * 0.003  # 預設保底 0.3%

            # ---------------- 訊號判定 ----------------
            # 買入：多頭趨勢 + 大盤向上 + 爆量急拉或超賣反轉
            if is_bull and qqq_change >= 0:
                sl = latest_close - (1.2 * atr)
                tp = latest_close + (1.8 * atr)
                if volume_surge and minute_change >= 0.7:
                    send_signal("BUY", ticker, latest_close, sl, tp, "多頭趨勢+大盤共振+爆量突破")
                    last_alert_time[ticker] = now
                elif rsi <= 25 and minute_change > 0.2:
                    send_signal("BUY", ticker, latest_close, sl, tp, "多頭回踩+超賣底背離反彈")
                    last_alert_time[ticker] = now

            # 賣出：空頭趨勢 + 大盤向下 + 爆量破位或超買反轉
            elif is_bear and qqq_change <= 0:
                sl = latest_close + (1.2 * atr)
                tp = latest_close - (1.8 * atr)
                if volume_surge and minute_change <= -0.7:
                    send_signal("SELL", ticker, latest_close, sl, tp, "空頭趨勢+大盤下殺+爆量破位")
                    last_alert_time[ticker] = now
                elif rsi >= 78 and minute_change < -0.2:
                    send_signal("SELL", ticker, latest_close, sl, tp, "空頭反彈受阻+過熱轉弱")
                    last_alert_time[ticker] = now

    except Exception as e:
        print(f"巡邏週期發生錯誤: {e}")

if __name__ == "__main__":
    print("啟動【專業量化 + ATR動態風控】高勝率盯盤系統...")
    while True:
        run_monitoring_cycle()
        time.sleep(60)
