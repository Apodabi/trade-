"""Shared loaders for the market-vs-model analysis (train-micro + validation only)."""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, MICRO_START, VALID
from features import G, eff_time
from windows import build
import model as M

BPS_EDGES = np.array([-np.inf, -20, -10, -5, -2, 2, 5, 10, 20, np.inf])
BPS_LABELS = ["<-20", "-20..-10", "-10..-5", "-5..-2", "-2..2", "2..5", "5..10", "10..20", ">20"]
TAU_EDGES = np.array([0, 10, 30, 60, 120, 300, 600, 900])
TAU_LABELS = ["0-10", "10-30", "30-60", "60-120", "120-300", "300-600", "600-900"]


def fee_pc(q, mult=1.0):
    """Taker fee per contract in dollars before order-level rounding (fee_type=quadratic, 0.07*P*(1-P))."""
    return 0.07 * mult * q * (1 - q)


def fee_order(n, q):
    """Total taker fee for an order of n contracts at price q, rounded up to the cent."""
    return np.ceil(0.07 * n * q * (1 - q) * 100 - 1e-9) / 100.0


class Ctx:
    def __init__(self, extra_gamma=None, base=None):
        self.g = g = base.g if base is not None else G()
        par = json.load(open(M.PARAMS)); self.beta = np.array(par["har_beta"]); self.par = par["calib"]
        if base is not None:
            W = base.W
        else:
            W = build(g)
            W = W[(W.date >= MICRO_START) & W.idx_ok].reset_index(drop=True)
            W["micro_split"] = np.where(W.date <= "2026-07-31", "train", "valid")
        self.W = W
        nW = len(W); off = np.arange(900)
        T = W.i0.values[:, None] + off[None, :]
        # sigma2 for every second of every window (chunked to bound memory)
        sig2 = np.empty(T.shape)
        for a in range(0, nW, 500):
            tt = T[a:a + 500].ravel(); sig2[a:a + 500] = M.sigma2(g, tt, self.beta).reshape(-1, 900)
        ie = np.repeat(W.ie.values, 900); K = np.repeat(W.K.values, 900); t = T.ravel()
        tau = ie - t
        mu = g.mu(t, ie)
        v = sig2.ravel() * eff_time(tau)
        Ks = K - 0.5e-4
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.log(mu / Ks) / np.sqrt(v)
        z = np.where(tau <= 0, np.where(mu >= Ks, 50.0, -50.0), z)
        if extra_gamma:                      # lead-lag augmentation: z += sum gamma * gap/sqrt(v)
            for (kind, sym, L), gam in extra_gamma.items():
                lb = np.log(g.binance(kind, sym)); x = lb[t] - lb[t - L]
                if sym == "XRPUSDT": x = x - (g.lr[t] - g.lr[t - L])
                z = z + gam * np.nan_to_num(x / np.sqrt(v))
        z = np.clip(z, -50, 50)
        s = np.asarray(self.par["scale"])[M.tau_bucket(tau)]
        self.p = stats.t.cdf(s * z, df=self.par["nu"]).astype(np.float32).reshape(nW, 900)   # p[w, s]: info through second i0+s
        self.dbps = ((mu - K) / K * 1e4).astype(np.float32).reshape(nW, 900)
        self.z = z.astype(np.float32).reshape(nW, 900)

    def trades(self):
        W = self.W
        fs = sorted(glob.glob(os.path.join(DATA, "trades", "*.parquet")))
        df = pd.concat([pd.read_parquet(f, columns=["ticker", "ts", "yes_price", "count", "taker_side", "block"]) for f in fs], ignore_index=True)
        df["ticker"] = df.ticker.astype("category")
        idx = pd.Series(np.arange(len(W)), index=W.ticker.values)
        df["wi"] = df.ticker.cat.codes.map(pd.Series(idx.reindex(df.ticker.cat.categories).values)).values
        df = df[df.wi.notna() & ~df.block].copy(); df["wi"] = df.wi.astype(int); df = df.drop(columns=["ticker"])
        ts = df.ts.astype("int64").values
        unit = 10**9 if str(df.ts.dtype).startswith("datetime64[ns") else 10**6
        df["tsf"] = ts / unit
        df["sec"] = (np.floor(df.tsf).astype(np.int64) - self.g.t0) - W.i0.values[df.wi.values]   # second offset in window
        df["side"] = np.where(df.taker_side == "yes", 1, -1)
        df["y"] = W.yes.values[df.wi.values]
        df["tauc"] = 900 - (df.tsf - self.g.t0 - W.i0.values[df.wi.values])                       # seconds to close
        df = df[(df.sec >= 2) & (df.sec < 900)].sort_values(["wi", "tsf"]).reset_index(drop=True)
        # model with 1s decision latency: info through second sec-1
        df["p"] = self.p[df.wi.values, df.sec.values - 1]
        df["dbps"] = self.dbps[df.wi.values, df.sec.values - 1]
        df = df.drop(columns=["taker_side", "block", "ts"])
        df["split"] = pd.Categorical(W.micro_split.values[df.wi.values]); df["date"] = pd.Categorical(W.date.values[df.wi.values])
        for c in ("yes_price", "count", "p", "dbps", "tauc"): df[c] = df[c].astype(np.float32)
        for c in ("sec", "side", "y", "wi"): df[c] = df[c].astype(np.int32)
        return df


def gate(pnl_by_window, contracts_by_window, dates, seed=1):
    """Pass-gate statistics from per-window net P&L ($) and contracts traded."""
    pnl = np.asarray(pnl_by_window, float); n = np.asarray(contracts_by_window, float); dates = np.asarray(dates)
    tr = n > 0
    out = {"windows_traded": int(tr.sum()), "days": int(len(set(dates[tr]))), "contracts": float(n.sum()), "net_pnl": float(pnl.sum())}
    if tr.sum() == 0: return out
    out["pnl_per_contract_c"] = float(100 * pnl.sum() / n.sum())
    d = pd.DataFrame({"d": dates[tr], "pnl": pnl[tr], "n": n[tr]}).groupby("d").sum()
    rng = np.random.default_rng(seed); k = len(d)
    idx = rng.integers(0, k, size=(10000, k))
    bs = 100 * d.pnl.values[idx].sum(1) / d.n.values[idx].sum(1)
    out["ci95_c"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
    cum = np.cumsum(pnl[tr]); out["max_drawdown"] = float(np.max(np.maximum.accumulate(np.concatenate([[0], cum])) - np.concatenate([[0], cum])))
    out["max_day_share"] = float(d.pnl.max() / pnl.sum()) if pnl.sum() > 0 else None
    out["win_rate_windows"] = float(np.mean(pnl[tr] > 0))
    out["pass"] = {"n": out["windows_traded"] >= 500 and out["days"] >= 40,
                   "expectancy": out["pnl_per_contract_c"] >= 1.0 and out["ci95_c"][0] > 0,
                   "drawdown": out["max_drawdown"] <= 1000,
                   "concentration": out["max_day_share"] is not None and out["max_day_share"] <= 0.20}
    out["pass"]["all"] = all(out["pass"].values())
    return out
