import yfinance as yf
import pandas as pd
import numpy as np
from tqdm import tqdm
import time
import requests

# ==============================
# 🔑 Discord設定
# ==============================
WEBHOOK_URL = "https://discord.com/api/webhooks/1492203923157811230/OqAP-la9X9IaUhhR978c-Z62MEhpsrAYcTyoPH_wsZzlOyDCQyWJ7VmlphUYg5MAuEws"

def send_discord(msg):
    try:
        requests.post(WEBHOOK_URL, json={"content": msg})
    except:
        print("Discord送信失敗")

# ==============================
# ⚙️ 設定
# ==============================
INITIAL_CAPITAL = 100000
RISK_PER_TRADE = 0.01

MIN_PRICE = 300
MAX_PRICE = 5000

CHUNK_SIZE = 50
SLEEP_TIME = 1

# ==============================
# 🧠 スコア
# ==============================
def calc_score(price, ma20, ma60, volume_ratio, high_ratio):
    score = 0
    if price > ma20 > ma60:
        score += 30
    score += min(volume_ratio * 10, 20)
    score += high_ratio * 50
    return score

# ==============================
# 🤖 フィルター
# ==============================
def ai_filter(volume_ratio, high_ratio, atr_ratio):
    return volume_ratio > 1.8 and high_ratio >= 1.0 and atr_ratio > 0.02

# ==============================
# 📊 ガチバックテスト
# ==============================
def backtest_real(hist, initial_capital=100000):

    capital = initial_capital
    wins = 0
    losses = 0
    total_return = 0
    trades = 0

    for i in range(60, len(hist) - 15):

        window = hist.iloc[:i]

        price = window["Close"].iloc[-1]

        ma20 = window["Close"].rolling(20).mean().iloc[-1]
        ma60 = window["Close"].rolling(60).mean().iloc[-1]

        if pd.isna(ma20) or pd.isna(ma60):
            continue

        if not (price > ma20 > ma60):
            continue

        vol_recent = window["Volume"].iloc[-1]
        vol_past = window["Volume"].iloc[-60:-5].mean()

        if pd.isna(vol_past) or vol_past == 0:
            continue

        volume_ratio = vol_recent / vol_past
        if volume_ratio < 1.8:
            continue

        recent_high = window["High"].rolling(20).max().iloc[-2]
        if pd.isna(recent_high):
            continue

        if not (recent_high * 0.99 <= price <= recent_high * 1.02):
            continue

        atr = (window["High"] - window["Low"]).rolling(14).mean().iloc[-1]
        if pd.isna(atr):
            continue

        entry = price
        stop = entry - atr
        target = entry + atr * 2

        risk_per_share = entry - stop
        if risk_per_share <= 0:
            continue

        risk_amount = capital * 0.01
        size = int(risk_amount / risk_per_share)
        size = (size // 100) * 100

        if size < 100:
            continue

        trades += 1

        future = hist.iloc[i:i+14]

        result = None

        for _, row in future.iterrows():
            if row["High"] >= target:
                profit = (target - entry) * size
                capital += profit
                wins += 1
                total_return += profit
                result = "win"
                break

            if row["Low"] <= stop:
                loss = (entry - stop) * size
                capital -= loss
                losses += 1
                total_return -= loss
                result = "loss"
                break

        if result is None:
            pass

        if capital <= 0:
            break

    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    expectancy = (total_return / trades) if trades > 0 else 0

    return trades, win_rate, capital, expectancy

# ==============================
# 🔍 メイン
# ==============================
def run():

    print("銘柄取得中...")

    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    df = pd.read_excel(url)

    codes = df["コード"].dropna().astype(str)
    codes = codes[codes.str.isdigit()]
    codes = codes[codes.str.len() == 4]

    tickers = [c + ".T" for c in codes]

    print(f"銘柄数: {len(tickers)}")

    data = {}
    chunks = [tickers[i:i+CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]

    print("データ取得中...")

    for chunk in tqdm(chunks):
        try:
            tmp = yf.download(chunk, period="6mo", group_by="ticker", progress=False, threads=False)

            if tmp is None or tmp.empty:
                continue

            if isinstance(tmp.columns, pd.MultiIndex):
                for t in chunk:
                    if t in tmp.columns.levels[0]:
                        data[t] = tmp[t]
            else:
                data[chunk[0]] = tmp

        except:
            pass

        time.sleep(SLEEP_TIME)

    print(f"取得成功銘柄数: {len(data)}")

    # ===== スクリーニング =====
    candidates = []

    for ticker in tqdm(data.keys()):
        try:
            hist = data[ticker]

            if len(hist) < 60:
                continue

            price = hist["Close"].iloc[-1]

            if not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            ma20 = hist["Close"].rolling(20).mean().iloc[-1]
            ma60 = hist["Close"].rolling(60).mean().iloc[-1]

            if pd.isna(ma20) or pd.isna(ma60):
                continue

            if not (price > ma20 > ma60):
                continue

            vol_recent = hist["Volume"].iloc[-1]
            vol_past = hist["Volume"].iloc[-60:-5].mean()

            if pd.isna(vol_past) or vol_past == 0:
                continue

            volume_ratio = vol_recent / vol_past

            recent_high = hist["High"].rolling(20).max().iloc[-2]
            if pd.isna(recent_high) or price <= recent_high:
                continue

            high_ratio = price / recent_high

            atr = (hist["High"] - hist["Low"]).rolling(14).mean().iloc[-1]
            atr_ratio = atr / price

            if not ai_filter(volume_ratio, high_ratio, atr_ratio):
                continue

            score = calc_score(price, ma20, ma60, volume_ratio, high_ratio)

            candidates.append((ticker, score))

        except:
            continue

    if len(candidates) == 0:
        msg = "⚠️ 該当銘柄なし"
        print(msg)
        send_discord(msg)
        return

    # ===== 最強1銘柄 =====
    best_ticker = sorted(candidates, key=lambda x: x[1], reverse=True)[0][0]
    hist = data[best_ticker]

    price = hist["Close"].iloc[-1]
    stop_price = price * 0.98
    take_profit = price * 1.06

    risk_amount = INITIAL_CAPITAL * RISK_PER_TRADE
    risk_per_share = price - stop_price

    if risk_per_share > 0:
        size = int(risk_amount / risk_per_share)
        size = (size // 100) * 100
    else:
        size = 0

    investment = size * price

    # ===== バックテスト =====
    trades, win_rate, final_capital, expectancy = backtest_real(hist)

    # ===== 出力 =====
    msg = f"""
🔥最強1銘柄🔥
銘柄: {best_ticker}
株価: {price:.1f}円

株数: {size}
投資額: {int(investment)}円

損切り: {stop_price:.2f}
利確: {take_profit:.2f}

📊 勝率: {win_rate:.2f}%
📈 期待値: {int(expectancy)}円
💰 最終資金: {int(final_capital)}円
"""

    print(msg)
    send_discord(msg)

# ==============================
# 🚀 実行
# ==============================
if __name__ == "__main__":
    run()
