"""Binance reference data at 1-second resolution (data.binance.vision bulk files).
spot: official 1s klines. perp (USD-M): built from aggTrades (no 1s klines published).
Output: data/binance/{kind}_{symbol}/{date}.npz with arrays of length 86400:
 px (last trade price in the second, forward-filled), vol (base volume),
 n (trade count; 0 => no trade that second)."""
import io, os, sys, zipfile, urllib.request, datetime as dt
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA
BASE = "https://data.binance.vision/data/"

def fetch(url):
    for k in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception:
            pass
    return None

def one(kind, sym, day):
    out = os.path.join(DATA, "binance", f"{kind}_{sym}"); os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, day + ".npz")
    if os.path.exists(fn): return "skip"
    d0 = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp())
    px = np.full(86400, np.nan); vol = np.zeros(86400); n = np.zeros(86400, dtype=np.int32)
    if kind == "spot":
        raw = fetch(f"{BASE}spot/daily/klines/{sym}/1s/{sym}-1s-{day}.zip")
        if raw is None: return "missing"
        df = pd.read_csv(zipfile.ZipFile(io.BytesIO(raw)).open(f"{sym}-1s-{day}.csv"), header=None)
        t = df[0].to_numpy()
        t = t // 1_000_000 if t[0] > 1e14 else t // 1000
        i = (t - d0).astype(int); ok = (i >= 0) & (i < 86400)
        px[i[ok]] = df[4].to_numpy()[ok]; vol[i[ok]] = df[5].to_numpy()[ok]; n[i[ok]] = df[8].to_numpy()[ok]
        px[n == 0] = np.nan  # kline exists but carries previous close; mark as no-trade
        last = df[4].to_numpy()
        pxff = np.full(86400, np.nan); pxff[i[ok]] = last[ok]
        px = pd.Series(pxff).ffill().to_numpy()
    else:
        raw = fetch(f"{BASE}futures/um/daily/aggTrades/{sym}/{sym}-aggTrades-{day}.zip")
        if raw is None: return "missing"
        df = pd.read_csv(zipfile.ZipFile(io.BytesIO(raw)).open(f"{sym}-aggTrades-{day}.csv"))
        i = (df["transact_time"].to_numpy() // 1000 - d0).astype(int)
        ok = (i >= 0) & (i < 86400); i = i[ok]; p = df["price"].to_numpy()[ok]; q = df["quantity"].to_numpy()[ok]
        px[i] = p  # last write wins -> last trade in each second (file is time-ordered)
        np.add.at(vol, i, q); np.add.at(n, i, 1)
        px = pd.Series(px).ffill().to_numpy()
    np.savez_compressed(fn, px=px, vol=vol, n=n)
    return "ok"

if __name__ == "__main__":
    start, end = sys.argv[1], sys.argv[2]
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(start, end)]
    jobs = [(k, s, d) for d in days for k in ("spot", "perp") for s in ("XRPUSDT", "BTCUSDT")]
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(lambda a: (a, one(*a)), jobs))
    bad = [a for a, r in res if r == "missing"]
    print("done", len(res), "missing", bad, flush=True)
