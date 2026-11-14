#!/usr/bin/env python3
"""1-second order-book recorder for the active KXXRP15M market.

READ-ONLY: issues only unauthenticated GETs to public market-data endpoints.
No API key, no order or portfolio calls.

Every second:   GET /markets/{ticker}/orderbook          (full depth, both sides)
Every window:   GET /markets?series_ticker=KXXRP15M&status=open  (find the active market)
Every 10 min:   GET /live_data/events/{event}            (per-second index for the trailing hour,
                                                          so the index is captured with overlap)
Output (append-only, one file per UTC day, gzip JSON lines):
  data/book/book-YYYY-MM-DD.jsonl.gz    {"ts": local epoch, "rt": request latency s, "ticker", "yes": [[px, sz],..], "no": [[px, sz],..]}
  data/book/index-YYYY-MM-DD.jsonl.gz   {"ts", "event", "t0_ms", "v": [...]}
  data/book/health.log                  one line per minute: snapshots ok / failed / empty book

Run for >= 14 days before modelling fills:
    nohup python3 recorder/record_book.py >> data/book/recorder.out 2>&1 &
It needs a host that stays up (this research container does not).
"""
import gzip, json, os, sys, time, datetime as dt, urllib.request, urllib.error

BASE = "https://api.elections.kalshi.com/trade-api/v2"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "book")
SERIES = "KXXRP15M"


def get(path, timeout=4):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "research-readonly/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def day(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d")


def append(kind, ts, obj):
    with gzip.open(os.path.join(OUT, f"{kind}-{day(ts)}.jsonl.gz"), "at") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def active_market():
    ms = get(f"/markets?series_ticker={SERIES}&status=open&limit=5", timeout=8).get("markets", [])
    now = time.time()
    ms = [m for m in ms if dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp() > now]
    if not ms:
        return None
    m = min(ms, key=lambda m: m["close_time"])
    return m["ticker"], m["event_ticker"], dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp()


def main(max_seconds=None):
    os.makedirs(OUT, exist_ok=True)
    start = time.time(); cur = None; last_idx = 0
    stats = {"ok": 0, "fail": 0, "empty": 0, "nomkt": 0}; last_min = int(start // 60)
    nxt = int(start) + 1
    while max_seconds is None or time.time() - start < max_seconds:
        time.sleep(max(0.0, nxt - time.time())); now = time.time(); nxt = int(now) + 1
        try:
            if cur is None or now >= cur[2]:
                cur = active_market()
            if cur is None:
                stats["nomkt"] += 1          # weekly pause / no listed window
            else:
                t1 = time.time()
                ob = get(f"/markets/{cur[0]}/orderbook")
                book = ob.get("orderbook_fp") or ob.get("orderbook") or {}
                yes = book.get("yes_dollars") or book.get("yes") or []
                no = book.get("no_dollars") or book.get("no") or []
                append("book", now, {"ts": round(now, 3), "rt": round(time.time() - t1, 3),
                                     "ticker": cur[0], "yes": yes, "no": no})
                stats["ok"] += 1; stats["empty"] += (not yes or not no)
                if now - last_idx > 600:
                    ld = get(f"/live_data/events/{cur[1]}", timeout=10)["live_data"]["details"]["timeseries"]
                    append("index", now, {"ts": round(now, 3), "event": cur[1], "t0_ms": ld[0]["t"],
                                          "v": [x["v"] for x in ld]})
                    last_idx = now
        except Exception as e:  # keep running through 429s, timeouts, maintenance
            stats["fail"] += 1
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                time.sleep(1.0)
        if int(now // 60) != last_min:
            with open(os.path.join(OUT, "health.log"), "a") as f:
                f.write(f"{dt.datetime.fromtimestamp(now, dt.UTC):%Y-%m-%dT%H:%M:%SZ} {json.dumps(stats)}\n")
            stats = {k: 0 for k in stats}; last_min = int(now // 60)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else None)
