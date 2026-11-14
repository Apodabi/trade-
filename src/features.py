"""Global per-second arrays + fair-value model primitives.

Time base: index i <-> epoch second t0+i. All arrays are aligned so that
element i is what was *true at* second t0+i:
  R[i]   raw RTI print at t0+i (deconvolved), A[i] trailing-60s mean (Kalshi series)
  BX*/BB* Binance XRPUSDT / BTCUSDT last trade at t0+i, i.e. close of the 1s
          bar labelled t0+i-1 (a bar labelled s covers [s, s+1)).
"""
import os, sys, datetime as dt
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA

TICK = 1e-5
G60 = sum((k / 60.0) ** 2 for k in range(1, 60))  # 19.50


def eff_time(tau):
    """Variance of the closing 60s average given info with tau seconds left,
    in units of one-second variance (random walk)."""
    tau = np.asarray(tau, dtype=np.float64)
    return np.where(tau >= 60, tau - 59 + G60, tau * (tau + 1) * (2 * tau + 1) / 21600.0)


class G:
    """Lazy global arrays (cached to data/global/*.npy)."""
    def __init__(self):
        z = np.load(os.path.join(DATA, "index.npz"))
        self.t0 = int(z["t0"]); self.S = z["S"]; self.R = z["R"]; self.present = z["present"]
        self.n = len(self.R)
        self.A = np.where(self.S >= 0, self.S * (TICK / 60.0), np.nan)
        self.lr = np.log(self.R)
        self._c = {}
        r = np.where(np.isnan(self.R), 0.0, self.R)
        self.cR = np.concatenate([[0.0], np.cumsum(r)])            # cR[i] = sum R[:i]
        self.cN = np.concatenate([[0], np.cumsum(~np.isnan(self.R))])

    def binance(self, kind, sym):
        key = f"{kind}_{sym}"
        if key in self._c: return self._c[key]
        cache = os.path.join(DATA, "global"); os.makedirs(cache, exist_ok=True)
        fn = os.path.join(cache, f"{key}_{self.t0}_{self.n}.npy")
        if os.path.exists(fn):
            a = np.load(fn)
        else:
            a = np.full(self.n, np.nan)
            d = dt.datetime.fromtimestamp(self.t0 - 1, dt.UTC).date()
            end = dt.datetime.fromtimestamp(self.t0 + self.n, dt.UTC).date()
            while d <= end:
                f = os.path.join(DATA, "binance", key, d.isoformat() + ".npz")
                if os.path.exists(f):
                    z = np.load(f); px = z["px"].astype(np.float64); nn = z["n"]
                    # staleness guard: no trade for >30s -> nan
                    last = np.maximum.accumulate(np.where(nn > 0, np.arange(86400), -10**9))
                    px[np.arange(86400) - last > 30] = np.nan
                    d0 = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp())
                    i = d0 + np.arange(86400) + 1 - self.t0        # bar label s -> true-at s+1
                    m = (i >= 0) & (i < self.n)
                    a[i[m]] = px[m]
                d += dt.timedelta(days=1)
            np.save(fn, a)
        self._c[key] = a
        return a

    # ---- volatility -------------------------------------------------
    def rv_roll(self, win, step=5):
        """Trailing mean of per-second variance estimates from `step`-second log returns."""
        key = ("rv", win, step)
        if key in self._c: return self._c[key]
        d = np.full(self.n, np.nan)
        d[step:] = (self.lr[step:] - self.lr[:-step]) ** 2 / step
        ok = ~np.isnan(d)
        c = np.concatenate([[0.0], np.cumsum(np.where(ok, d, 0.0))])
        k = np.concatenate([[0], np.cumsum(ok)])
        i = np.arange(self.n)
        lo = np.maximum(i + 1 - win, 0)
        cnt = k[i + 1] - k[lo]
        out = np.where(cnt >= 0.5 * win, (c[i + 1] - c[lo]) / np.maximum(cnt, 1), np.nan)
        self._c[key] = out
        return out

    def rv_fwd(self, win, step=5):
        key = ("rvf", win, step)
        if key in self._c: return self._c[key]
        tr = self.rv_roll(win, step)
        out = np.full(self.n, np.nan)
        out[:-win] = tr[win:]                                        # trailing at t+win covers (t, t+win]
        self._c[key] = out
        return out

    # ---- settlement primitives -------------------------------------
    def mu(self, t, T):
        """E[closing 60s mean | info through second t] under a martingale, for close index T."""
        t = np.asarray(t); T = np.asarray(T)
        tau = T - t
        lo = np.maximum(T - 59, 0)
        hi = np.minimum(t, T) + 1
        nobs = np.where(tau < 60, 60 - tau, 0)
        psum = np.where(tau < 60, self.cR[hi] - self.cR[np.minimum(lo, hi)], 0.0)
        good = (self.cN[hi] - self.cN[np.minimum(lo, hi)]) == nobs
        m = (psum + (60 - nobs) * self.R[t]) / 60.0
        return np.where(good, m, np.nan)
