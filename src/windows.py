"""Window table: one row per KXXRP15M market with index-derived checks."""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from common import load_markets, DATA
from features import G, TICK

def build(g=None):
    g = g or G()
    m = load_markets()
    m = m[m.status.isin(["finalized", "settled"]) | m.result.isin(["yes", "no"])].copy()
    m["i0"] = (m.open_ts.astype("int64") // 10**9 if str(m.open_ts.dtype).endswith("ns, UTC]") else m.open_ts.map(lambda x: int(x.timestamp()))) - g.t0
    m["i1"] = m.close_ts.map(lambda x: int(x.timestamp())) - g.t0
    m["i0"] = m.open_ts.map(lambda x: int(x.timestamp())) - g.t0
    m = m[(m.i0 >= 60) & (m.i1 < g.n)].copy()
    m["yes"] = (m.result == "yes").astype(int)
    m["K"] = m.floor_strike.astype(float)
    # Verified empirically: the settlement print is the series value stamped T-1
    # (mean of the 60 RTI prints stamped T-60..T-1); the target is the same thing
    # for the open time, i.e. the previous window's expiration value.
    m["ie"] = m.i1 - 1
    m["A0"] = g.A[m.i0.values - 1]; m["A1"] = g.A[m.ie.values]
    m["expv"] = pd.to_numeric(m.expiration_value, errors="coerce")
    m["K_missing"] = m.K.isna()
    m["K"] = m.K.fillna(np.round(m.A0 + 1e-12, 4))
    m["dur"] = m.i1 - m.i0
    # index complete over [i0-60, i1]?
    cN = g.cN
    m["idx_ok"] = (cN[m.i1.values] - cN[m.i0.values - 60]) == (m.i1.values - m.i0.values + 60)
    return m.reset_index(drop=True)

if __name__ == "__main__":
    w = build()
    w.to_parquet(os.path.join(DATA, "windows.parquet"), index=False)
    print(len(w), w.split.value_counts().to_dict())
