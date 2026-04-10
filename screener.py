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

# RR設定（超重要）
STOP_LOSS = 0.98
TAKE_PROFIT = 1.06   # RR=3

HOLD_DAYS = 10

# ==============================
# 🧠 スコア
# ==============================
def calc_score(win_rate, volume_ratio, high_ratio):
    score = 0
    score += win_rate * 50
    score += min(volume_ratio * 10, 20)
    score += high_ratio * 30
    return score

# ==============================
# 🤖 フィルター（緩め）
# ==============================
def ai_filter(volume_ratio, atr_ratio):
    return volume_ratio > 1.2 and atr_ratio > 0.015

# ==============================
# 📊 バックテスト関数（超重要）
# ==============================
def backtest(hist):

    wins = 0
    losses = 0

    for i in range(60, len(hist) - HOLD_DAYS):

        price = hist["Close"].iloc[i]

        ma20 = hist["Close"].rolling(20).mean().iloc[i]
        ma60 = hist["Close"].rolling(60).mean().iloc[i]

        if pd.isna(ma20) or pd.isna(ma60):
            continue

        # 押し目条件（改善ポイント）
        if not (price > ma20 > ma60):
            continue

        recent_high = hist["High"].rolling(20).max().iloc[i-1]
        if price > recent_high:
            continue  # ★追いかけ禁止

        vol_recent = hist["Volume"].iloc[i]
        vol_past = hist["Volume"].iloc[i-60:i-5].mean()

        if pd.isna(vol_past) or vol_past == 0:
            continue

        volume_ratio = vol_recent / vol_past

        atr = (hist["High"] - hist["Low"]).rolling(14).mean().iloc[i]
        atr_ratio = atr / price

        if not ai_filter(volume_ratio, atr_ratio):
            continue

        # ===== トレード =====
        entry = price
        tp = entry * TAKE_PROFIT
        sl = entry * STOP_LOSS

        future = hist.iloc[i:i+HOLD_DAYS]

        for _, row in future.iterrows():
            if row["High"] >= tp:
                wins += 1
                break
            if row["Low"] <= sl:
                losses += 1
                break

    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0

    return win_rate, total

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

    # ===== データ取得 =====
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

    # ==============================
    # 🔍 スクリーニング＋バックテスト
    # ==============================
    candidates = []

    for ticker in tqdm(data.keys()):
        try:
            hist = data[ticker]

            if len(hist) < 100:
                continue

            price = hist["Close"].iloc[-1]

            if not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            # ===== 勝率計算 =====
            win_rate, trades = backtest(hist)

            if trades < 5:
                continue

            # ===== 現在条件 =====
            ma20 = hist["Close"].rolling(20).mean().iloc[-1]
            ma60 = hist["Close"].rolling(60).mean().iloc[-1]

            if not (price > ma20 > ma60):
                continue

            vol_recent = hist["Volume"].iloc[-1]
            vol_past = hist["Volume"].iloc[-60:-5].mean()

            if pd.isna(vol_past) or vol_past == 0:
                continue

            volume_ratio = vol_recent / vol_past

            recent_high = hist["High"].rolling(20).max().iloc[-2]
            high_ratio = price / recent_high

            score = calc_score(win_rate, volume_ratio, high_ratio)

            candidates.append({
                "ticker": ticker,
                "price": price,
                "win_rate": win_rate,
                "score": score
            })

        except:
            continue

    if len(candidates) == 0:
        msg = "⚠️ 該当銘柄なし"
        print(msg)
        send_discord(msg)
        return

    # ===== 最強銘柄 =====
    df = pd.DataFrame(candidates)
    df = df.sort_values("score", ascending=False)

    best = df.iloc[0]

    price = best["price"]
    stop_price = price * STOP_LOSS
    take_profit = price * TAKE_PROFIT

    risk_amount = INITIAL_CAPITAL * RISK_PER_TRADE
    risk_per_share = price - stop_price

    if risk_per_share > 0:
        size = int(risk_amount / risk_per_share)
        size = (size // 100) * 100
    else:
        size = 0

    investment = size * price

    # ==============================
    # 📢 出力
    # ==============================
    msg = f"""
🔥最強1銘柄（勝率ベース）🔥
銘柄: {best['ticker']}
株価: {price:.1f}円

株数: {size}
投資額: {int(investment)}円

損切り: {stop_price:.2f}
利確: {take_profit:.2f}

📊 勝率: {best['win_rate']:.2f}%
"""

    print(msg)
    send_discord(msg)

# ==============================
# 🚀 実行
# ==============================
if __name__ == "__main__":
    run()