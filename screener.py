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
# 🤖 フィルター
# ==============================
def ai_filter(volume_ratio, high_ratio, atr_ratio):
    return volume_ratio > 1.5 and high_ratio >= 1.0 and atr_ratio > 0.02

# ==============================
# 📊 バックテスト
# ==============================
def backtest(hist):
    wins = 0
    losses = 0
    total_profit = 0

    for i in range(60, len(hist) - 10):

        entry = hist["Close"].iloc[i]
        tp = entry * 1.05
        sl = entry * 0.98

        future = hist.iloc[i:i+10]

        for _, row in future.iterrows():
            if row["High"] >= tp:
                wins += 1
                total_profit += (tp - entry)
                break
            if row["Low"] <= sl:
                losses += 1
                total_profit += (sl - entry)
                break

    total = wins + losses

    if total == 0:
        return 0, 0, 0

    win_rate = wins / total * 100
    expectancy = total_profit / total

    return win_rate, expectancy, total

# ==============================
# 🚀 メイン
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
    # 🔍 スクリーニング
    # ==============================
    results = []

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

            # ===== バックテスト =====
            win_rate, expectancy, trades = backtest(hist)

            if trades < 5:
                continue

            results.append({
                "ticker": ticker,
                "price": price,
                "win_rate": win_rate,
                "expectancy": expectancy,
                "trades": trades
            })

        except:
            continue

    if len(results) == 0:
        msg = "⚠️ 条件に合う優良銘柄なし"
        print(msg)
        send_discord(msg)
        return

    df = pd.DataFrame(results)

    # ★勝率ベースで並び替え（ここ変えれば期待値順にもできる）
    df = df.sort_values(["win_rate", "expectancy"], ascending=False)

    # ==============================
    # 📢 出力（TOP3）
    # ==============================
    msg = "🔥本日の有望銘柄TOP3🔥\n\n"

    for _, row in df.head(3).iterrows():

        ticker = row["ticker"]
        price = row["price"]
        win_rate = row["win_rate"]
        expectancy = row["expectancy"]
        trades = row["trades"]

        # ===== ロット計算 =====
        stop_price = price * 0.98
        take_profit = price * 1.05

        risk_amount = INITIAL_CAPITAL * RISK_PER_TRADE
        risk_per_share = price - stop_price

        if risk_per_share > 0:
            size = int(risk_amount / risk_per_share)
            size = (size // 100) * 100
        else:
            size = 0

        investment = size * price

        msg += f"""
-----------------------------
銘柄: {ticker}
株価: {price:.1f}円

株数: {size}
投資額: {int(investment)}円

損切り: {stop_price:.2f}
利確: {take_profit:.2f}

📊 勝率: {win_rate:.1f}%
📈 期待値: {expectancy:.2f}
📊 トレード数: {trades}
"""

    print(msg)
    send_discord(msg)

# ==============================
# 実行
# ==============================
if __name__ == "__main__":
    run()
