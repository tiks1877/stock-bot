import time
import requests
import yfinance as yf
import pandas as pd

TELEGRAM_TOKEN = "8829545402:AAFFPm1WGXlIFlicOyzMg97CoptIJ_KiGmg"
TELEGRAM_CHAT_ID = "5267209755"
TECH_GIANTS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "TSLA"]
PRICE_JUMP_THRESHOLD = 0.8  

def send_telegram_alert(signal_type, ticker, price, change_pct, reason):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    headers = {
        "PUMP": "⚡ *【突發急拉暴漲 關注】* 🚀",
        "DUMP": "🚨 *【突發跳水暴跌 警戒】* 🩸",
        "OVERSOLD": "🛒 *【極度超賣抄底機會】* 🟢",
        "OVERBOUGHT": "⚠ *【極度過熱逃頂警戒】* 🔴"
    }
    header = headers.get(signal_type, "📢 *【行情提醒】*")
    text = (
        f"{header}\n━━━━━━━━━━━━━━━━━━\n"
        f"💻 *標的*：`{ticker}`\n"
        f"💵 *即時價格*：`${price:.2f}`\n"
        f"📊 *短線變動*：`{change_pct:+.2f}%`\n"
        f"💡 *異動原因*：{reason}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *觸發時間*：{time.strftime('%H:%M:%S')}"
    )
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
        print(f"已發送 {ticker} 警報至 Telegram")
    except Exception as e:
        print(f"推播失敗: {e}")

def check_stock(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="1m", prepost=True, progress=False)
        if df.empty or len(df) < 20:
            print(f"[{ticker}] 暫無足夠 1 分鐘線數據")
            return

        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(ticker, axis=1, level=1)

        latest_close = float(df['Close'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2])
        minute_change = ((latest_close - prev_close) / prev_close) * 100

        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        print(f"{ticker}: ${latest_close:.2f} | 變動: {minute_change:+.2f}% | RSI: {rsi:.1f}")

        if minute_change >= PRICE_JUMP_THRESHOLD:
            send_telegram_alert("PUMP", ticker, latest_close, minute_change, f"1分鐘急拉 +{minute_change:.2f}%")
        elif minute_change <= -PRICE_JUMP_THRESHOLD:
            send_telegram_alert("DUMP", ticker, latest_close, minute_change, f"1分鐘跳水 {minute_change:.2f}%")
        elif rsi <= 20:
            send_telegram_alert("OVERSOLD", ticker, latest_close, minute_change, f"RSI 極端超賣 ({rsi:.1f})")
        elif rsi >= 82:
            send_telegram_alert("OVERBOUGHT", ticker, latest_close, minute_change, f"RSI 極端超買 ({rsi:.1f})")
    except Exception as e:
        print(f"檢查 {ticker} 出錯: {e}")

if __name__ == "__main__":
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 開始執行美股科技巨頭巡邏...")
    for ticker in TECH_GIANTS:
        check_stock(ticker)
    print("巡邏完畢！")
