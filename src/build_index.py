"""Assemble the per-second index from hourly chunks and recover the raw
1-second RTI by deconvolving the trailing-60s mean.

Kalshi's series A_t is the mean of the last 60 one-second RTI prints, so
S_t = 60*A_t (in 1e-5 USD ticks) is an integer and
    R_t - R_{t-60} = S_t - S_{t-1}.
Within a gap-free segment this pins R down up to a 60-periodic pattern with
59 free parameters. We choose it by least squares on the roughness of R
(adjacent-phase mean increments = 0), which is consistent because true 1-second
increments do not depend on the phase within the minute.

Output data/index.npz:
  t0      epoch second of element 0
  S       int64 trailing-60s sum in 1e-5 ticks (-1 = missing)
  R       float64 raw RTI estimate in USD (nan = missing/unrecoverable)
"""
import glob, os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA

TICK = 1e-5
MIN_SEG = 2 * 3600  # need a couple of hours to identify the 60-periodic component
WARM = 60           # seconds after a gap during which the trailing mean is not a clean 60-sum


def deconvolve(S):
    """S: int64 contiguous trailing sums. Returns R (float ticks), same length;
    first 0 elements are defined as R_t for t>=0 where R_0 is the print at S[0]'s second."""
    n = len(S)
    D = np.diff(S).astype(np.float64)  # D[i] = R_{i+1} - R_{i-59}
    # C[t] = cumulative sum of D along each phase, with C=0 for the 60 initial values
    # index u = t + 59 for t in [-59, n-1]
    L = n + 59
    C = np.zeros(L)
    for k in range(60):
        idx = np.arange(k + 60, L, 60)          # positions u with t = u-59 >= 1 in phase k
        # R_t (t>=1) = R_{t-60} + D[t-1]; u = t+59 -> D index = u-60
        C[idx] = np.cumsum(D[idx - 60])
    # roughness: (b_{p(u)} - b_{p(u-1)}) + (C[u]-C[u-1]); p(u) = u % 60
    dC = np.diff(C)                              # for u = 1..L-1
    ph = np.arange(1, L) % 60
    delta = np.array([-dC[ph == k].mean() for k in range(60)])  # b_k - b_{k-1}
    delta -= delta.mean()                        # cycle constraint
    b = np.cumsum(delta)                         # b_0 = delta_0 + b_59 ... fix level below
    # b indexed by phase k (k=0..59); b_k - b_{k-1} = delta_k, with b_{-1} = b_59
    b = b - b[59]                                # so that b_0 - b_59 = delta_0 holds
    lvl = (S[0] - (b[np.arange(60) % 60] + C[:60]).sum()) / 60.0
    R = b[np.arange(L) % 60] + C + lvl
    return R[59:]


def main():
    files = sorted(glob.glob(os.path.join(DATA, "index", "raw", "*.npz")))
    tmin, tmax, bad = None, None, 0
    chunks = []
    for f in files:
        z = np.load(f)
        t, v = z["t"], z["v"]
        if len(t) == 0:
            bad += 1; continue
        chunks.append((t, v))
        tmin = t[0] if tmin is None else min(tmin, t[0]); tmax = t[-1] if tmax is None else max(tmax, t[-1])
    t0 = int(tmin // 1000); n = int(tmax // 1000) - t0 + 1
    S = np.full(n, -1, dtype=np.int64)
    offgrid = 0; resid = 0.0; nonint = 0
    for t, v in chunks:
        offgrid += int((t % 1000 != 0).sum())
        i = (t // 1000 - t0).astype(np.int64)
        s = v * 60.0 / TICK
        si = np.rint(s).astype(np.int64)
        resid = max(resid, float(np.abs(s[:-1] - si[:-1]).max()))
        good = np.abs(s - si) < 1e-3             # a clean 60-sum is an integer number of ticks
        nonint += int((~good[:-1]).sum())
        S[i[:-1][good[:-1]]] = si[:-1][good[:-1]]  # last point is the rounded settlement print
        if S[i[-1]] < 0:
            S[i[-1]] = -2                        # mark; filled below only if nothing better
    S[S == -2] = -1
    ok = S >= 0
    present = ok.copy()
    # invalidate the warm-up after every gap
    gap_end = np.flatnonzero(ok[1:] & ~ok[:-1]) + 1
    for g in gap_end:
        ok[g:g + WARM] = False
    R = np.full(n, np.nan)
    # contiguous segments
    edges = np.flatnonzero(np.diff(np.concatenate([[0], ok.astype(np.int8), [0]])))
    segs = list(zip(edges[::2], edges[1::2]))
    short = 0
    for a, b_ in segs:
        if b_ - a < MIN_SEG:
            short += b_ - a; continue
        R[a:b_] = deconvolve(S[a:b_]) * TICK
    Sraw = S.copy(); S = np.where(ok, S, -1)
    np.savez_compressed(os.path.join(DATA, "index.npz"), t0=t0, S=S, R=R, present=present, Sraw=Sraw)
    print(f"chunks={len(chunks)} empty={bad} span={n}s missing={int((~ok).sum())} segments={len(segs)} "
          f"short_unrecovered={short}s offgrid_ts={offgrid} nonint={nonint} present_missing={int((~present).sum())}")
    import datetime as dt
    for a, b_ in segs[:0]:
        f = lambda x: dt.datetime.fromtimestamp(t0 + x, dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
        print("  seg", f(a), "->", f(b_ - 1), b_ - a)

if __name__ == "__main__":
    main()
