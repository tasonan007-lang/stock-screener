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

MIN_WIN_RATE = 40
MIN_EXPECTANCY = 1.2
MIN_PF = 1.3
MIN_RR = 1.5

# ==============================
# 📈 地合い
# ==============================
def market_ok():
    try:
        nikkei = yf.download("^N225", period="5d", progress=False)

        if nikkei is None or nikkei.empty:
            return False

        close = nikkei["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        return float(close.iloc[-1]) > float(close.iloc[-2])

    except:
        return False

# ==============================
# 🤖 フィルター
# ==============================
def ai_filter(volume_ratio, high_ratio, atr_ratio):
    return volume_ratio > 1.5 and high_ratio >= 0.97 and atr_ratio > 0.02

# ==============================
# 📊 改良バックテスト（リアルRR）
# ==============================
def backtest(hist):

    trades = []

    for i in range(60, len(hist) - 10):

        entry = hist["Close"].iloc[i]
        tp = entry * 1.05
        sl = entry * 0.98

        future = hist.iloc[i:i+10]

        exit_price = None

        for _, row in future.iterrows():
            if row["High"] >= tp:
                exit_price = tp
                break
            if row["Low"] <= sl:
                exit_price = sl
                break

        if exit_price is None:
            continue

        pnl = exit_price - entry
        trades.append(pnl)

    if len(trades) == 0:
        return 0, 0, 0, 0, 0, 0, 0

    df = pd.Series(trades)

    wins = df[df > 0]
    losses = df[df < 0]

    total = len(df)
    win_rate = len(wins) / total * 100

    avg_profit = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0

    real_rr = abs(avg_profit / avg_loss) if avg_loss != 0 else 0

    expectancy = df.mean()

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    pf = gross_profit / gross_loss if gross_loss != 0 else 0

    return win_rate, expectancy, total, real_rr, avg_profit, avg_loss, pf

# ==============================
# 🚀 メイン
# ==============================
def run():

    print("地合いチェック中...")

    if not market_ok():
        msg = "⚠️ 地合いNG（トレード回避）"
        print(msg)
        send_discord(msg)
        return

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

            # ギャップ除外
            open_price = hist["Open"].iloc[-1]
            prev_close = hist["Close"].iloc[-2]
            if open_price > prev_close * 1.03:
                continue

            # トレンド
            ma20 = hist["Close"].rolling(20).mean().iloc[-1]
            ma60 = hist["Close"].rolling(60).mean().iloc[-1]

            if pd.isna(ma20) or pd.isna(ma60):
                continue

            if not (price > ma20 > ma60):
                continue

            # 出来高
            vol_recent = hist["Volume"].iloc[-1]
            vol_prev = hist["Volume"].iloc[-2]
            vol_past = hist["Volume"].iloc[-60:-5].mean()

            if pd.isna(vol_past) or vol_past == 0:
                continue

            volume_ratio = vol_recent / vol_past

            if vol_prev < vol_past:
                continue

            # ブレイク or 押し目
            recent_high = hist["High"].rolling(20).max().iloc[-5]
            if pd.isna(recent_high):
                continue

            high_ratio = price / recent_high

            is_breakout = price > recent_high * 0.99
            pullback = abs(price - ma20) / ma20
            is_pullback = (price < recent_high and pullback < 0.03)

            if not (is_breakout or is_pullback):
                continue

            # ATR
            atr = (hist["High"] - hist["Low"]).rolling(14).mean().iloc[-1]
            atr_ratio = atr / price

            if not ai_filter(volume_ratio, high_ratio, atr_ratio):
                continue

            # エントリー
            if is_breakout:
                entry_type = "ブレイク"
                entry_price = price
            else:
                entry_type = "押し目"
                entry_price = ma20 * 0.995

            # ===== バックテスト =====
            win_rate, expectancy, trades, real_rr, avg_profit, avg_loss, pf = backtest(hist)

            if trades < 5:
                continue
            if win_rate < MIN_WIN_RATE:
                continue
            if expectancy < MIN_EXPECTANCY:
                continue
            if pf < MIN_PF:
                continue
            if real_rr < MIN_RR:
                continue

            results.append({
                "ticker": ticker,
                "price": price,
                "entry_type": entry_type,
                "entry_price": entry_price,
                "win_rate": win_rate,
                "expectancy": expectancy,
                "trades": trades,
                "real_rr": real_rr,
                "avg_profit": avg_profit,
                "avg_loss": avg_loss,
                "pf": pf
            })

        except:
            continue

    if len(results) == 0:
        msg = "⚠️ 優良銘柄なし"
        print(msg)
        send_discord(msg)
        return

    df = pd.DataFrame(results)
    df = df.sort_values(["expectancy", "pf"], ascending=False)

    # ==============================
    # 📢 出力
    # ==============================
    msg = "🔥最強銘柄TOP3🔥\n"

    for _, row in df.head(3).iterrows():

        price = row["entry_price"]

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
銘柄: {row['ticker']}
エントリー: {row['entry_type']}

現在価格: {row['price']:.1f}円
👉 エントリー価格: {row['entry_price']:.2f}円

株数: {size}
投資額: {int(investment)}円

損切り: {stop_price:.2f}
利確: {take_profit:.2f}

📊 勝率: {row['win_rate']:.1f}%
📈 期待値: {row['expectancy']:.2f}
📊 トレード数: {row['trades']}

📊 リアルRR: {row['real_rr']:.2f}
💰 平均利益: {row['avg_profit']:.2f}
💸 平均損失: {row['avg_loss']:.2f}
📊 PF: {row['pf']:.2f}
"""

    print(msg)
    send_discord(msg)

# ==============================
# 実行
# ==============================
if __name__ == "__main__":
    run()
