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
    data = {"content": msg}
    try:
        requests.post(WEBHOOK_URL, json=data)
    except:
        print("Discord送信失敗")

# ==============================
# ⚙️ 設定
# ==============================
INITIAL_CAPITAL = 100000
RISK_PER_TRADE = 0.01

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
# 🤖 AIフィルター
# ==============================
def ai_filter(volume_ratio, high_ratio, atr_ratio):
    return volume_ratio > 2.0 and high_ratio >= 1.0 and atr_ratio > 0.025

# ==============================
# 🔍 メイン処理
# ==============================
def run_screener():

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
            tmp = yf.download(chunk, period="3mo", group_by="ticker", progress=False, threads=False)

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

    # ===== スキャン =====
    candidates = []

    for ticker in tqdm(data.keys()):
        try:
            hist = data[ticker]

            if len(hist) < 60:
                continue

            price = hist["Close"].iloc[-1]

            ma20 = hist["Close"].rolling(20).mean().iloc[-1]
            ma60 = hist["Close"].rolling(60).mean().iloc[-1]

            if pd.isna(ma20) or pd.isna(ma60):
                continue

            if not (price > ma20 > ma60):
                continue

            # 出来高
            vol_recent = hist["Volume"].iloc[-1]
            vol_past = hist["Volume"].iloc[-60:-5].mean()

            if pd.isna(vol_past) or vol_past == 0:
                continue

            volume_ratio = vol_recent / vol_past

            # 高値ブレイク
            recent_high = hist["High"].rolling(20).max().iloc[-2]
            if pd.isna(recent_high) or price <= recent_high:
                continue

            high_ratio = price / recent_high

            # ATR
            atr = (hist["High"] - hist["Low"]).rolling(14).mean().iloc[-1]
            atr_ratio = atr / price

            # 上ヒゲ除外
            upper_shadow = hist["High"].iloc[-1] - hist["Close"].iloc[-1]
            body = abs(hist["Close"].iloc[-1] - hist["Open"].iloc[-1])
            if upper_shadow > body:
                continue

            if not ai_filter(volume_ratio, high_ratio, atr_ratio):
                continue

            score = calc_score(price, ma20, ma60, volume_ratio, high_ratio)

            candidates.append({
                "ticker": ticker,
                "price": price,
                "score": score,
                "volume_ratio": volume_ratio,
                "high_ratio": high_ratio,
                "atr_ratio": atr_ratio
            })

        except:
            continue

    # ===== 結果 =====
    if len(candidates) == 0:
        msg = "⚠️ 今日の該当銘柄なし"
        print(msg)
        send_discord(msg)
        return

    df = pd.DataFrame(candidates)
    df = df.sort_values("score", ascending=False)

    best = df.iloc[0]

    price = best["price"]
    stop_price = price * 0.98
    take_profit = price * 1.05

    # ロット計算
    risk_amount = INITIAL_CAPITAL * RISK_PER_TRADE
    risk_per_share = price - stop_price

    if risk_per_share > 0:
        raw_size = int(risk_amount / risk_per_share)
        position_size = (raw_size // 100) * 100
    else:
        position_size = 0

    investment = position_size * price

    msg = f"""
🔥今日の最強1銘柄🔥
銘柄: {best['ticker']}
株価: {price:.1f}円

株数: {position_size}
投資額: {int(investment)}円

損切り: {stop_price:.2f}
利確: {take_profit:.2f}

スコア: {best['score']:.2f}
出来高倍率: {best['volume_ratio']:.2f}
高値位置: {best['high_ratio']:.3f}
ボラ: {best['atr_ratio']:.3f}
"""

    print(msg)
    send_discord(msg)

# ==============================
# 🚀 実行（これが重要）
# ==============================
if __name__ == "__main__":
    run_screener()
