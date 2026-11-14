"""Download every KXXRP15M market (historical + live tiers) to data/markets.csv."""
import csv, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from kalshi import Client

FIELDS = ["ticker", "event_ticker", "open_time", "close_time", "status", "result",
          "floor_strike", "expiration_value", "round_digits", "strike_type",
          "volume_fp", "open_interest_fp", "settlement_ts", "last_price_dollars",
          "price_level_structure", "rules_primary", "tier"]

def main(out="data/markets.csv"):
    c = Client(min_interval=0.6)
    rows = {}
    for tier, path in (("historical", "/historical/markets"), ("live", "/markets")):
        n = 0
        for m in c.paged(path, "markets", limit=1000, series_ticker="KXXRP15M"):
            m["round_digits"] = (m.get("custom_strike") or {}).get("round_digits")
            m["tier"] = tier
            rows[m["ticker"]] = {k: m.get(k) for k in FIELDS}
            n += 1
        print(tier, n, "calls", c.n_calls, "429s", c.n_429, flush=True)
    rs = sorted(rows.values(), key=lambda r: r["close_time"])
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rs)
    print("wrote", len(rs), rs[0]["close_time"], rs[-1]["close_time"])

if __name__ == "__main__":
    main()
