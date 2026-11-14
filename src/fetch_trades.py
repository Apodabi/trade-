"""Download the public trade tape for KXXRP15M markets, one parquet per UTC day.
Scope: MICRO_START .. end of validation (holdout never requested)."""
import os, sys, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from kalshi import Client
from common import load_markets, DATA, MICRO_START, VALID

def main():
    out = os.path.join(DATA, "trades"); os.makedirs(out, exist_ok=True)
    m = load_markets()
    m = m[(m.date >= MICRO_START) & (m.date <= VALID[1])]
    c = Client(min_interval=float(os.environ.get("IVL", "0.9")))
    cut = pd.Timestamp(c.get("/historical/cutoff")["trades_created_ts"])
    days = sorted(m.date.unique())
    days = [d for d in days if d >= VALID[0]] + [d for d in days if d < VALID[0]][::-1]
    k, n = map(int, os.environ.get('PART', '0/1').split('/'))
    days = days[k::n]
    if os.environ.get('REV'): days = days[::-1]
    for day in days:
        fn = os.path.join(out, day + ".parquet")
        if os.path.exists(fn):
            continue
        rows = []
        for r in m[m.date == day].itertuples():
            paths = ["/historical/trades"] if r.close_ts < cut else ["/markets/trades"]
            if abs((r.close_ts - cut).total_seconds()) < 86400:
                paths = ["/historical/trades", "/markets/trades"]
            seen = set()
            for p in paths:
                for t in c.paged(p, "trades", limit=1000, ticker=r.ticker):
                    if t["trade_id"] in seen: continue
                    seen.add(t["trade_id"])
                    rows.append((r.ticker, t["created_time"], float(t["yes_price_dollars"]),
                                 float(t["count_fp"]), t["taker_side"], bool(t.get("is_block_trade"))))
        df = pd.DataFrame(rows, columns=["ticker", "ts", "yes_price", "count", "taker_side", "block"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        df.sort_values("ts").to_parquet(fn, index=False)
        print(day, len(df), "calls", c.n_calls, "429", c.n_429, "ivl %.2f" % c.interval, flush=True)

if __name__ == "__main__":
    main()
