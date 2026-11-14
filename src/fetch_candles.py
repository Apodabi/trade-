"""1-minute bid/ask candlesticks for a deterministic 1-in-6 sample of windows
in the microstructure period (used for spread statistics only)."""
import os, sys, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from kalshi import Client
from common import load_markets, DATA, MICRO_START, VALID

def main():
    out = os.path.join(DATA, "candles"); os.makedirs(out, exist_ok=True)
    m = load_markets()
    m = m[(m.date >= MICRO_START) & (m.date <= VALID[1])]
    import glob
    have = set()
    for f in glob.glob(os.path.join(out, "*.parquet")):
        have |= set(pd.read_parquet(f, columns=["ticker"]).ticker.unique())
    m = m[~m.ticker.isin(have)].sample(frac=1.0, random_state=7) if os.environ.get("ALL") else m.iloc[::6]
    tag = os.environ.get("TAG", "candles")
    c = Client(min_interval=0.3)
    cut = pd.Timestamp(c.get("/historical/cutoff")["market_settled_ts"])
    k, n = map(int, os.environ.get("PART", "0/1").split("/"))
    rows = []
    fn = os.path.join(out, f"{tag}_{k}of{n}.parquet")
    def flush():
        df = pd.DataFrame(rows, columns=["ticker", "end_ts", "bid", "ask", "bid_low", "ask_high", "last", "volume"])
        for col in df.columns[2:]: df[col] = pd.to_numeric(df[col], errors="coerce")
        df.to_parquet(fn + ".tmp", index=False); os.replace(fn + ".tmp", fn)
        return len(df)
    for j, r in enumerate(list(m.itertuples())[k::n]):
        a, b = int(r.open_ts.timestamp()), int(r.close_ts.timestamp())
        paths = [f"/historical/markets/{r.ticker}/candlesticks", f"/series/KXXRP15M/markets/{r.ticker}/candlesticks"]
        if r.close_ts >= cut: paths = paths[::-1]
        for p in paths:
            d = c.get(p, start_ts=a, end_ts=b, period_interval=1)
            cs = (d or {}).get("candlesticks") or []
            if cs: break
        for x in cs:
            g = lambda o, f: (x.get(o) or {}).get(f) or (x.get(o) or {}).get(f + "_dollars")
            rows.append((r.ticker, x["end_period_ts"], g("yes_bid", "close"), g("yes_ask", "close"),
                         g("yes_bid", "low"), g("yes_ask", "high"), g("price", "close"),
                         x.get("volume") or x.get("volume_fp")))
        if j % 100 == 0:
            print(j, r.ticker, len(rows), "calls", c.n_calls, "429", c.n_429, flush=True)
        if j % 150 == 149: flush()
    print("done", flush(), flush=True)

if __name__ == "__main__":
    main()
