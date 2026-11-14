"""Fair-value model for KXXRP15M.

P(yes | t) = P( mean(R[T-60..T-1]) >= K - 0.00005 | info through second t )

  mu_t   = E[closing mean]  = (sum of closing-window prints already seen + (#unseen) * R_t) / 60
  v_t    = sigma2_t * eff_time(tau)     (tau = seconds until the final print)
  z_t    = ln(mu_t / K*) / sqrt(v_t)
  P      = T_nu( s_b * z_t )            (Student-t CDF, scale s_b per tau-bucket; nu, s_b fit on train)

sigma2_t is a HAR-style forecast of per-second variance over the next 15 minutes.
"""
import os, sys, json
import numpy as np, pandas as pd
from scipy import stats, optimize
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA
from features import G, eff_time

TAU_EDGES = np.array([0, 10, 30, 60, 120, 300, 600, 901])
HAR_WINS = (300, 900, 3600, 21600, 86400)
RV_STEP = 30
PARAMS = os.path.join(DATA, "model_params.json")


def tau_bucket(tau):
    return np.clip(np.searchsorted(TAU_EDGES, tau, side="right") - 1, 0, len(TAU_EDGES) - 2)


def har_X(g, t):
    cols = [np.log(g.rv_roll(w, RV_STEP)[t]) for w in HAR_WINS]
    hr = ((g.t0 + t) // 3600) % 24
    H = np.zeros((len(t), 24)); H[np.arange(len(t)), hr] = 1.0
    return np.column_stack(cols + [H])


def fit_har(g, t_train):
    X = har_X(g, t_train); y = np.log(g.rv_fwd(900, RV_STEP)[t_train])
    ok = np.isfinite(X).all(1) & np.isfinite(y)
    beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    resid = y[ok] - X[ok] @ beta
    r2 = 1 - resid.var() / y[ok].var()
    return beta, float(r2), int(ok.sum())


def sigma2(g, t, beta):
    return np.exp(har_X(g, t) @ beta)


def zscore(g, t, ie, K, beta, naive=False):
    tau = ie - t
    if naive:   # what a chart-watcher would do: displayed trailing mean, variance ~ time left
        m = g.A[t]; v = sigma2(g, t, beta) * np.maximum(tau, 1)
    else:
        m = g.mu(t, ie); v = sigma2(g, t, beta) * eff_time(tau)
    Ks = K - 0.5e-4
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.log(m / Ks) / np.sqrt(v)
    # tau == 0: outcome known
    z = np.where(tau <= 0, np.where(m >= Ks, 50.0, -50.0), z)
    return np.clip(z, -50, 50)


def prob(z, tau, par):
    s = np.asarray(par["scale"])[tau_bucket(tau)]
    return stats.t.cdf(s * z, df=par["nu"])


def fit_calib(z, tau, y):
    b = tau_bucket(tau); nb = len(TAU_EDGES) - 1
    ok = np.isfinite(z)
    z, b, y = z[ok], b[ok], y[ok]
    def nll(p):
        nu = 2 + np.exp(p[0]); s = np.exp(p[1:])
        q = np.clip(stats.t.cdf(s[b] * z, df=nu), 1e-6, 1 - 1e-6)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
    r = optimize.minimize(nll, np.zeros(nb + 1), method="L-BFGS-B")
    return {"nu": float(2 + np.exp(r.x[0])), "scale": [float(v) for v in np.exp(r.x[1:])], "nll": float(r.fun)}


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def sample_panel(g, w, step=5):
    """Rows every `step` seconds for each window; returns dict of arrays."""
    off = np.arange(0, 900, step)
    wi = np.repeat(np.arange(len(w)), len(off))
    t = (w.i0.values[:, None] + off[None, :]).ravel()
    ie = w.ie.values[wi]
    return dict(wi=wi, t=t, ie=ie, tau=ie - t, K=w.K.values[wi], y=w.yes.values[wi].astype(float))
