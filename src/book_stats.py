"""Descriptive statistics from the live 1-second book recorder (displayed size, spread)."""
import glob, gzip, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA
rows = []
for f in sorted(glob.glob(os.path.join(DATA, "book", "book-*.jsonl.gz"))):
    for line in gzip.open(f, "rt"):
        try: x = json.loads(line)
        except Exception: continue
        y = [(float(p), float(s)) for p, s in x["yes"]]; n = [(float(p), float(s)) for p, s in x["no"]]
        if not y or not n: rows.append((x["ts"], x["ticker"], np.nan, np.nan, 0, 0, x["rt"])); continue
        bb = max(y); bn = max(n)
        rows.append((x["ts"], x["ticker"], bb[0], 1 - bn[0], bb[1], bn[1], x["rt"]))
a = np.array([(r[0], r[2], r[3], r[4], r[5], r[6]) for r in rows], float)
tick = [r[1] for r in rows]
out = {"snapshots": len(rows), "first_ts": float(a[0, 0]), "last_ts": float(a[-1, 0]), "span_min": float((a[-1, 0] - a[0, 0]) / 60),
       "coverage": float(len(rows) / max(1, a[-1, 0] - a[0, 0])), "windows": len(set(tick)),
       "one_sided_or_empty_share": float(np.isnan(a[:, 1]).mean()),
       "spread_c": {q: float(100 * np.nanpercentile(a[:, 2] - a[:, 1], q)) for q in (10, 50, 90)},
       "best_bid_size": {q: float(np.nanpercentile(a[:, 3], q)) for q in (10, 50, 90)},
       "best_ask_size": {q: float(np.nanpercentile(a[:, 4], q)) for q in (10, 50, 90)},
       "request_latency_s": {q: float(np.percentile(a[:, 5], q)) for q in (50, 95, 99)}}
json.dump(out, open(os.path.join(DATA, "results_book.json"), "w"), indent=1); print(json.dumps(out, indent=1))

# ---- depth: how much size sits at the best quote, and what 10 / 100 contracts would cost ----
def px_for(levels, need):
    cum = 0.0; cost = 0.0
    for p, s in levels:
        take = min(s, need - cum); cost += take * p; cum += take
        if cum >= need - 1e-9: return cost / need
    return np.nan
d = []
for f in sorted(glob.glob(os.path.join(DATA, "book", "book-*.jsonl.gz"))):
    for line in gzip.open(f, "rt"):
        try: x = json.loads(line)
        except Exception: continue
        y = sorted([(float(p), float(s)) for p, s in x["yes"]], reverse=True); n = sorted([(float(p), float(s)) for p, s in x["no"]], reverse=True)
        if not y or not n: continue
        d.append((y[0][0], y[0][1], 1 - n[0][0], n[0][1], px_for(y, 10), 1 - px_for(n, 10), px_for(y, 100), 1 - px_for(n, 100)))
b = np.array(d)
depth = {"snapshots_two_sided": len(b), "all": {
    "share_best_bid_lt10": float((b[:, 1] < 10).mean()), "share_best_ask_lt10": float((b[:, 3] < 10).mean()),
    "spread_best_c_mean": float(100 * np.mean(b[:, 2] - b[:, 0])),
    "slip_10lot_buy_c_mean": float(100 * np.nanmean(b[:, 5] - b[:, 2])), "slip_10lot_sell_c_mean": float(100 * np.nanmean(b[:, 0] - b[:, 4])),
    "slip_100lot_buy_c_mean": float(100 * np.nanmean(b[:, 7] - b[:, 2])), "slip_100lot_sell_c_mean": float(100 * np.nanmean(b[:, 0] - b[:, 6]))}}
json.dump(depth, open(os.path.join(DATA, "results_book_depth.json"), "w"), indent=1); print(json.dumps(depth, indent=1))
