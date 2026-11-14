"""Download Kalshi's per-second XRP index series (trailing-60s mean of
CF Benchmarks XRPUSD_RTI) in 1-hour chunks, one per top-of-hour event.

Each /live_data/events/{event} response holds 3601 one-second points ending at
the event's maturity. Values are sums of 60 RTI prints / 60, so we store the
exact integer S = round(v * 60 * 1e5) (units: 1e-5 USD * 60).
Resumable: one .npz per event in data/index/raw/.
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from kalshi import Client
from common import load_markets, DATA

def main():
    out = os.path.join(DATA, "index", "raw"); os.makedirs(out, exist_ok=True)
    m = load_markets()
    m = m[(m.close_ts.dt.minute == 0)]
    c = Client(min_interval=float(os.environ.get("IVL", "0.9")))
    todo = [(r.event_ticker, int(r.close_ts.timestamp())) for r in m.itertuples()
            if not os.path.exists(os.path.join(out, r.event_ticker + ".npz"))]
    if os.environ.get("NEWEST_FIRST"): todo = todo[::-1]
    print("todo", len(todo), flush=True)
    for i, (ev, close) in enumerate(todo):
        if os.path.exists(os.path.join(out, ev + ".npz")): continue
        d = c.get(f"/live_data/events/{ev}")
        ts = ((d or {}).get("live_data", {}).get("details", {}) or {}).get("timeseries") or []
        t = np.array([x["t"] for x in ts], dtype=np.int64)
        v = np.array([x["v"] for x in ts], dtype=np.float64)
        np.savez_compressed(os.path.join(out, ev + ".npz"), t=t, v=v, close=close)
        if i % 100 == 0:
            print(i, ev, len(ts), "calls", c.n_calls, "429", c.n_429, "ivl %.2f" % c.interval, flush=True)

if __name__ == "__main__":
    main()
