"""Fit the fair-value model on train, evaluate on validation, test signals one at a time.
Writes data/model_params.json, data/results_model.json, figures/calibration.png."""
import os, sys, json
import numpy as np, pandas as pd
from scipy import stats, optimize
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, ROOT
from features import G, eff_time
from windows import build
import model as M

OUT = {}
g = G(); W = build(g)
OUT["windows_total"] = int(len(W)); OUT["windows_idx_ok"] = int(W.idx_ok.sum())
OUT["by_split"] = {s: {"n": int((W.split == s).sum()), "idx_ok": int(((W.split == s) & W.idx_ok).sum()),
                       "yes_rate": float(W[W.split == s].yes.mean())} for s in ("train", "valid")}
W = W[W.idx_ok].reset_index(drop=True)
W["dayi"] = pd.factorize(W.date)[0]
tr = W[W.split == "train"].reset_index(drop=True); va = W[W.split == "valid"].reset_index(drop=True)

# ---------------- volatility model ----------------
t_tr = np.concatenate([np.arange(a, b, 300) for a, b in zip(tr.i0.values, tr.i1.values)])
beta, r2, n = M.fit_har(g, t_tr)
t_va = np.concatenate([np.arange(a, b, 300) for a, b in zip(va.i0.values, va.i1.values)])
Xv = M.har_X(g, t_va); yv = np.log(g.rv_fwd(900, M.RV_STEP)[t_va]); ok = np.isfinite(Xv).all(1) & np.isfinite(yv)
r2v = 1 - np.var(yv[ok] - Xv[ok] @ beta) / np.var(yv[ok])
OUT["har"] = {"r2_train": r2, "r2_valid": float(r2v), "n_train": n, "coef_logrv": dict(zip(map(str, M.HAR_WINS), map(float, beta[:5])))}
print("HAR", OUT["har"])

# ---------------- baseline calibration ----------------
Ptr = M.sample_panel(g, tr, 5); Pva = M.sample_panel(g, va, 5)
res = {}
for name, naive in (("naive_chart", True), ("full", False)):
    ztr = M.zscore(g, Ptr["t"], Ptr["ie"], Ptr["K"], beta, naive); zva = M.zscore(g, Pva["t"], Pva["ie"], Pva["K"], beta, naive)
    par = M.fit_calib(ztr, Ptr["tau"], Ptr["y"])
    r = {"nu": par["nu"], "scale": par["scale"]}
    for sp, P, z in (("train", Ptr, ztr), ("valid", Pva, zva)):
        p = M.prob(z, P["tau"], par); okk = np.isfinite(z); b = M.tau_bucket(P["tau"])
        r[sp] = {"logloss": M.logloss(p[okk], P["y"][okk]), "brier": float(np.mean((p[okk] - P["y"][okk]) ** 2)),
                 "by_tau": [M.logloss(p[okk & (b == k)], P["y"][okk & (b == k)]) for k in range(7)]}
    res[name] = r
    if not naive:
        PAR = par; Ptr["z"] = ztr; Pva["z"] = zva
OUT["baseline"] = res; OUT["tau_edges"] = M.TAU_EDGES.tolist()
json.dump({"har_beta": beta.tolist(), "calib": PAR, "rv_step": M.RV_STEP, "har_wins": M.HAR_WINS}, open(M.PARAMS, "w"))
print(json.dumps(res, indent=1)[:1500])

# ---------------- calibration table / chart (validation) ----------------
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
edges = np.linspace(0, 1, 11)
cal = {}
fig, ax = plt.subplots(1, 2, figsize=(11, 4.8))
for sp, P, a in (("train", Ptr, ax[0]), ("valid", Pva, ax[1])):
    p = M.prob(P["z"], P["tau"], PAR)
    a.plot([0, 1], [0, 1], color="#888", lw=1, ls="--")
    for tau0, col in ((600, "#1f4e79"), (300, "#2e86ab"), (120, "#5aa469"), (60, "#e09f3e"), (30, "#c1440e")):
        m = (P["tau"] >= tau0 - 4) & (P["tau"] <= tau0) & np.isfinite(P["z"])     # one row per window
        bins = np.clip(np.digitize(p[m], edges) - 1, 0, 9)
        rows = []
        for k in range(10):
            mm = bins == k
            if mm.sum() < 30: continue
            f = P["y"][m][mm].mean(); nn = int(mm.sum())
            rows.append((float(p[m][mm].mean()), float(f), nn, float(1.96 * np.sqrt(max(f * (1 - f), 1e-9) / nn))))
        cal[f"{sp}_tau{tau0}"] = rows
        r = np.array(rows)
        a.errorbar(r[:, 0], r[:, 1], yerr=r[:, 3], marker="o", ms=3.5, lw=1.2, color=col, label=f"{tau0}s left", capsize=2)
    a.set_title(f"{sp}: model probability vs settled-Yes frequency"); a.set_xlabel("model P(Yes), decile bins"); a.set_ylabel("observed Yes frequency")
    a.legend(frameon=False, fontsize=8); a.grid(alpha=.25)
plt.tight_layout(); os.makedirs(os.path.join(ROOT, "figures"), exist_ok=True)
plt.savefig(os.path.join(ROOT, "figures", "calibration.png"), dpi=150); plt.close()
OUT["calibration"] = cal
# pooled validation calibration table (all sampled rows)
p = M.prob(Pva["z"], Pva["tau"], PAR); okk = np.isfinite(Pva["z"]); bins = np.clip(np.digitize(p, edges) - 1, 0, 9)
OUT["calibration_valid_pooled"] = [(float(p[okk & (bins == k)].mean()), float(Pva["y"][okk & (bins == k)].mean()), int((okk & (bins == k)).sum())) for k in range(10)]

# ---------------- signal tests (one at a time) ----------------
def sub(P, step=3):
    m = (np.arange(len(P["t"])) % step == 0) & np.isfinite(P["z"]) & (P["tau"] >= 10)
    return {k: v[m] for k, v in P.items()}
Str, Sva = sub(Ptr), sub(Pva)
for S, w in ((Str, tr), (Sva, va)):
    S["v"] = M.sigma2(g, S["t"], beta) * eff_time(S["tau"]); S["day"] = w.dayi.values[S["wi"]]
    S["p0"] = M.prob(S["z"], S["tau"], PAR)

def ll_rows(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6); return -(y * np.log(p) + (1 - y) * np.log(1 - p))

def test_signal(name, Dtr, Dva, mode="add", mask_tr=None, mask_va=None):
    """z' = z + D@gamma (add) or z*exp(D@gamma) (mul). Fit gamma on train."""
    mtr = np.isfinite(Dtr).all(1) if mask_tr is None else mask_tr & np.isfinite(Dtr).all(1)
    mva = np.isfinite(Dva).all(1) if mask_va is None else mask_va & np.isfinite(Dva).all(1)
    s_tr = np.asarray(PAR["scale"])[M.tau_bucket(Str["tau"][mtr])]; s_va = np.asarray(PAR["scale"])[M.tau_bucket(Sva["tau"][mva])]
    def pr(gam, z, D, s):
        zz = z + D @ gam if mode == "add" else z * np.exp(D @ gam)
        return stats.t.cdf(s * zz, df=PAR["nu"])
    f = lambda gam: ll_rows(pr(gam, Str["z"][mtr], Dtr[mtr], s_tr), Str["y"][mtr]).mean()
    r = optimize.minimize(f, np.zeros(Dtr.shape[1]), method="L-BFGS-B")
    out = {"gamma": [float(x) for x in r.x], "n_train": int(mtr.sum()), "n_valid": int(mva.sum())}
    for sp, S, D, m, s in (("train", Str, Dtr, mtr, s_tr), ("valid", Sva, Dva, mva, s_va)):
        d = ll_rows(pr(r.x, S["z"][m], D[m], s), S["y"][m]) - ll_rows(S["p0"][m], S["y"][m])
        day = pd.Series(d).groupby(S["day"][m]).mean()
        out[sp] = {"dlogloss": float(d.mean()), "t_day": float(day.mean() / (day.std(ddof=1) / np.sqrt(len(day)))), "days": int(len(day))}
        b = M.tau_bucket(S["tau"][m]); out[sp]["by_tau"] = [float(d[b == k].mean()) if (b == k).any() else None for k in range(7)]
    out["kept"] = bool(out["train"]["dlogloss"] < 0 and out["valid"]["dlogloss"] < 0)
    OUT.setdefault("signals", {})[name] = out
    print(f"{name:28s} gamma={np.round(r.x[:4], 4)} dLL train={out['train']['dlogloss']:+.5f} (t={out['train']['t_day']:+.1f}) "
          f"valid={out['valid']['dlogloss']:+.5f} (t={out['valid']['t_day']:+.1f}) kept={out['kept']}", flush=True)
    return out

# (1) lead-lag: regression table first
BXp, BXs, BBp, BBs = (g.binance(k, s) for k, s in (("perp", "XRPUSDT"), ("spot", "XRPUSDT"), ("perp", "BTCUSDT"), ("spot", "BTCUSDT")))
lB = {"xrp_perp": np.log(BXp), "xrp_spot": np.log(BXs), "btc_perp": np.log(BBp), "btc_spot": np.log(BBs)}
LAGS = (1, 2, 5, 10, 30, 60); HORIZ = (1, 5, 10, 30, 60)
def leadlag(w):
    t = np.concatenate([np.arange(a + 61, b - 61, 15) for a, b in zip(w.i0.values, w.i1.values)])
    day = np.repeat(w.dayi.values, [len(np.arange(a + 61, b - 61, 15)) for a, b in zip(w.i0.values, w.i1.values)])
    rows = []
    for nm, lb in lB.items():
        for L in LAGS:
            x = lb[t] - lb[t - L]
            if nm.startswith("xrp"): x = x - (g.lr[t] - g.lr[t - L])        # Binance-minus-index gap
            for h in HORIZ:
                y = g.lr[t + h] - g.lr[t]
                m = np.isfinite(x) & np.isfinite(y)
                xs, ys = x[m], y[m]
                b = (xs * ys).sum() / (xs * xs).sum()
                r2_ = 1 - ((ys - b * xs) ** 2).sum() / (ys ** 2).sum()
                df = pd.DataFrame({"xy": xs * ys, "xx": xs * xs, "d": day[m]}).groupby("d").sum()
                bd = df.xy / df.xx
                rows.append({"src": nm, "L": L, "h": h, "beta": float(b), "r2": float(r2_), "t_day": float(bd.mean() / (bd.std(ddof=1) / np.sqrt(len(bd)))), "n": int(m.sum())})
    return pd.DataFrame(rows)
ll_tr = leadlag(tr); ll_va = leadlag(va)
ll = ll_tr.merge(ll_va, on=["src", "L", "h"], suffixes=("_tr", "_va"))
ll.to_csv(os.path.join(DATA, "leadlag.csv"), index=False)
print(ll[ll.h.isin([1, 10, 60])].pivot_table(index=["src", "L"], columns="h", values=["beta_tr", "r2_tr"]).round(4).to_string())

def gapfeat(S, nm, L):
    x = lB[nm][S["t"]] - lB[nm][S["t"] - L]
    if nm.startswith("xrp"): x = x - (g.lr[S["t"]] - g.lr[S["t"] - L])
    return (x / np.sqrt(S["v"]))[:, None]
for nm in lB:
    best = ll_tr[(ll_tr.src == nm) & (ll_tr.h == 30)].sort_values("r2", ascending=False).iloc[0]
    L = int(best.L)
    test_signal(f"leadlag_{nm}_L{L}", gapfeat(Str, nm, L), gapfeat(Sva, nm, L))
# BTC on top of XRP's own Binance gap: test BTC after absorbing the xrp_perp gap into z
bestx = int(ll_tr[(ll_tr.src == "xrp_perp") & (ll_tr.h == 30)].sort_values("r2", ascending=False).iloc[0].L)
bestb = int(ll_tr[(ll_tr.src == "btc_perp") & (ll_tr.h == 30)].sort_values("r2", ascending=False).iloc[0].L)
test_signal("leadlag_xrp_perp+btc_perp", np.hstack([gapfeat(Str, "xrp_perp", bestx), gapfeat(Str, "btc_perp", bestb)]),
            np.hstack([gapfeat(Sva, "xrp_perp", bestx), gapfeat(Sva, "btc_perp", bestb)]))

# (3) previous-window momentum / reversal
for S, w in ((Str, tr), (Sva, va)):
    prevA = g.A[w.i0.values - 901]; sd15 = np.sqrt(M.sigma2(g, w.i0.values, beta) * 900)
    S["prev_ret"] = (np.log(w.A0.values / prevA) / sd15)[S["wi"]]
    S["prev_sign"] = np.sign(S["prev_ret"])
test_signal("prev_window_return", Str["prev_ret"][:, None], Sva["prev_ret"][:, None])
test_signal("prev_window_return_first5min", Str["prev_ret"][:, None], Sva["prev_ret"][:, None], mask_tr=Str["tau"] >= 600, mask_va=Sva["tau"] >= 600)
test_signal("prev_window_outcome_sign", Str["prev_sign"][:, None], Sva["prev_sign"][:, None])

# (4) volatility regime (terciles of forecast sigma at the sampled time, train thresholds)
sg_tr = np.log(M.sigma2(g, Str["t"], beta)); sg_va = np.log(M.sigma2(g, Sva["t"], beta))
q = np.nanquantile(sg_tr, [1 / 3, 2 / 3])
def terc(s): 
    k = np.digitize(s, q); D = np.zeros((len(s), 3)); D[np.arange(len(s)), k] = 1.0; D[~np.isfinite(s)] = np.nan; return D
test_signal("vol_regime_scale", terc(sg_tr), terc(sg_va), mode="mul")
test_signal("vol_regime_bias", terc(sg_tr), terc(sg_va), mode="add")

# (5) time of day / day of week
def dummies(S, kind):
    ts = g.t0 + S["t"]
    k = (ts // 3600) % 24 if kind == "hour" else ((ts // 86400) + 3) % 7      # 1970-01-01 was a Thursday -> Mon=0
    n = 24 if kind == "hour" else 7
    D = np.zeros((len(ts), n)); D[np.arange(len(ts)), k] = 1.0; return D
for kind in ("hour", "dow"):
    test_signal(f"{kind}_bias", dummies(Str, kind), dummies(Sva, kind))
    test_signal(f"{kind}_scale", dummies(Str, kind), dummies(Sva, kind), mode="mul")
# raw Yes rate by hour / dow (window level)
for sp, w in (("train", tr), ("valid", va)):
    hr = w.open_ts.dt.hour; dw = w.open_ts.dt.dayofweek
    OUT[f"yes_by_hour_{sp}"] = w.groupby(hr).yes.agg(["mean", "count"]).round(4).values.tolist()
    OUT[f"yes_by_dow_{sp}"] = w.groupby(dw).yes.agg(["mean", "count"]).round(4).values.tolist()
    OUT[f"tie_rate_{sp}"] = float(np.mean(np.abs(w.expv - w.K) < 1e-9))
json.dump(OUT, open(os.path.join(DATA, "results_model.json"), "w"), indent=1)
print("saved")
