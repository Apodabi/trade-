"""Model vs Kalshi market: calibration of prices, edge grids, and the three
pre-registered strategy configs. Train-micro = 2026-06-01..07-31, validation = 08-01..09-30.
Writes data/results_market.json and figures/edge_grid.png."""
import os, sys, json, glob
import numpy as np, pandas as pd
from scipy import stats, optimize
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, ROOT
import model as M
from market import *

OUT = {}
RM = json.load(open(os.path.join(DATA, "results_model.json")))
C = Ctx(); W = C.W; g = C.g
T = C.trades()
print("windows", len(W), W.micro_split.value_counts().to_dict(), "trades", len(T), flush=True)
OUT["n_windows"] = W.micro_split.value_counts().to_dict(); OUT["n_trades"] = T.split.value_counts().to_dict()
OUT["contracts"] = T.groupby("split")["count"].sum().to_dict()
tw = T.groupby("wi").agg(n=("count", "size"), vol=("count", "sum"))
OUT["per_window"] = {sp: {"median_trades": float(tw.n[W.micro_split.values[tw.index] == sp].median()),
                          "median_contracts": float(tw.vol[W.micro_split.values[tw.index] == sp].median()),
                          "windows_with_trades": int((W.micro_split.values[tw.index] == sp).sum())} for sp in ("train", "valid")}

q = T.yes_price.values; s = T.side.values; y = T.y.values; n = T["count"].values
T["fee"] = fee_pc(q)
T["taker_pnl"] = s * (y - q) - T.fee          # per contract, taker who printed this trade
T["maker_pnl"] = -s * (y - q)                 # per contract, resting side (maker fee = 0 for this series)
T["edge"] = s * (T.p.values - q) - T.fee      # model EV of copying the taker, 1s-stale model
T["tb"] = np.clip(np.searchsorted(TAU_EDGES, T.tauc.values, side="right") - 1, 0, 6)
T["db"] = np.clip(np.searchsorted(BPS_EDGES, T.dbps.values, side="right") - 1, 0, 8)

def wmean(x, w): return float(np.sum(x * w) / np.sum(w)) if np.sum(w) > 0 else None

# ---- (A) what did takers / makers actually earn? ----
for sp in ("train", "valid"):
    d = T[T.split == sp]
    OUT[f"aggregate_{sp}"] = {"taker_pnl_c": 100 * wmean(d.taker_pnl, d["count"]), "maker_pnl_c": 100 * wmean(d.maker_pnl, d["count"]),
                              "fee_c": 100 * wmean(d.fee, d["count"]), "model_edge_c": 100 * wmean(d.edge, d["count"]),
                              "share_prints_model_edge_pos": float((d.edge > 0).mean())}
    day = d.assign(tp=d.taker_pnl * d["count"]).groupby("date").agg(tp=("tp", "sum"), n=("count", "sum"))
    r = 100 * day.tp / day.n
    OUT[f"aggregate_{sp}"]["taker_pnl_day_t"] = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))
print(json.dumps({k: v for k, v in OUT.items() if k.startswith("aggregate")}, indent=1), flush=True)

for sp in ("train", "valid"):
    d = T[T.split == sp]
    OUT[f"by_tau_{sp}"] = [{"tau": TAU_LABELS[k], "contracts": float(x["count"].sum()), "taker_pnl_c": 100 * wmean(x.taker_pnl, x["count"]),
                            "maker_pnl_c": 100 * wmean(x.maker_pnl, x["count"]), "fee_c": 100 * wmean(x.fee, x["count"])} for k, x in d.groupby("tb")]
# ---- (B) market price calibration at prints (contract-weighted) ----
pe = np.array([0, .02, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, .98, 1.0001])
T["pb"] = np.clip(np.searchsorted(pe, q, side="right") - 1, 0, len(pe) - 2)
for sp in ("train", "valid"):
    d = T[T.split == sp]
    OUT[f"price_calibration_{sp}"] = [{"bin": f"{pe[k]:.2f}-{min(pe[k+1],1):.2f}", "mean_price": wmean(x.yes_price, x["count"]), "yes_freq": wmean(x.y, x["count"]),
                                       "contracts": float(x["count"].sum()), "windows": int(x.wi.nunique())} for k, x in d.groupby("pb")]

# ---- (C) edge grids: tau x distance ----
def grid(d, col, cond=None):
    A = np.full((7, 9), np.nan); N = np.zeros((7, 9))
    d = d[np.isfinite(d[col].values) & np.isfinite(d.edge.values)]
    if cond is not None: d = d[cond(d)]
    for (tb, db), x in d.groupby(["tb", "db"]):
        w = np.minimum(x["count"].values, 100.0)
        A[tb, db] = 100 * np.sum(x[col].values * w) / w.sum(); N[tb, db] = x.wi.nunique()
    return A, N
G_ = {}
for sp in ("train", "valid"):
    d = T[T.split == sp]
    for nm, col, cond in (("model_edge", "edge", None), ("taker_realized", "taker_pnl", None),
                          ("realized_when_edge_ge2c", "taker_pnl", lambda x: x.edge >= 0.02)):
        A, N = grid(d, col, cond); G_[f"{nm}_{sp}"] = A; OUT[f"grid_{nm}_{sp}"] = {"cents": np.round(A, 2).tolist(), "windows": N.astype(int).tolist()}
OUT["grid_axes"] = {"tau": TAU_LABELS, "dist_bps": BPS_LABELS}

# ---- (D) quotes sample: spread, and model vs mid (user's definition: |model - mid| - half spread - fee) ----
QG = {}
cf = [f for f in glob.glob(os.path.join(DATA, "candles", "*.parquet")) if not f.endswith(".tmp")]
if cf:
    Cd = pd.concat([pd.read_parquet(f) for f in cf], ignore_index=True).drop_duplicates(["ticker", "end_ts"])
    idx = pd.Series(np.arange(len(W)), index=W.ticker.values); Cd["wi"] = Cd.ticker.map(idx); Cd = Cd[Cd.wi.notna()].copy(); Cd["wi"] = Cd.wi.astype(int)
    Cd["sec"] = Cd.end_ts - g.t0 - W.i0.values[Cd.wi.values]
    Cd = Cd[(Cd.sec >= 60) & (Cd.sec <= 840) & Cd.bid.notna() & Cd.ask.notna() & (Cd.ask > Cd.bid) & (Cd.bid > 0) & (Cd.ask < 1)].copy()
    # pre-registered 1s latency: decide with index data through E-1, trade the quote standing at E
    Cd["p"] = C.p[Cd.wi.values, Cd.sec.values.astype(int) - 1].astype(float); Cd["p_lat0"] = C.p[Cd.wi.values, Cd.sec.values.astype(int)].astype(float)
    Cd = Cd[np.isfinite(Cd.p) & np.isfinite(Cd.p_lat0)].copy(); Cd["y"] = W.yes.values[Cd.wi.values]; Cd["split"] = W.micro_split.values[Cd.wi.values]
    Cd["dbps"] = C.dbps[Cd.wi.values, Cd.sec.values.astype(int)]; Cd["date"] = W.date.values[Cd.wi.values]
    Cd["mid"] = (Cd.bid + Cd.ask) / 2; Cd["spread"] = Cd.ask - Cd.bid
    buy = Cd.p - Cd.ask - fee_pc(Cd.ask); sell = Cd.bid - Cd.p - fee_pc(Cd.bid)
    Cd["edge"] = np.maximum(buy, sell); Cd["dir"] = np.where(buy >= sell, 1, -1)
    Cd["real"] = np.where(Cd.dir == 1, Cd.y - Cd.ask - fee_pc(Cd.ask), Cd.bid - Cd.y - fee_pc(Cd.bid))
    Cd["tb"] = np.clip(np.searchsorted(TAU_EDGES, 900 - Cd.sec.values, side="right") - 1, 0, 6)
    Cd["db"] = np.clip(np.searchsorted(BPS_EDGES, Cd.dbps.values, side="right") - 1, 0, 8)
    for sp in ("train", "valid"):
        d = Cd[Cd.split == sp]
        o = {"windows": int(d.wi.nunique()), "rows": int(len(d)), "median_spread_c": float(100 * d.spread.median()), "mean_spread_c": float(100 * d.spread.mean()),
             "spread_by_min": (100 * d.groupby("sec").spread.mean()).round(2).to_dict(),
             "mean_edge_c": float(100 * d.edge.mean()), "share_edge_pos": float((d.edge > 0).mean()),
             "logloss_model": M.logloss(d.p.values, d.y.values), "logloss_mid": M.logloss(d.mid.values, d.y.values),
             "brier_model": float(np.mean((d.p - d.y) ** 2)), "brier_mid": float(np.mean((d.mid - d.y) ** 2))}
        b0 = d.p_lat0 - d.ask - fee_pc(d.ask); s0 = d.bid - d.p_lat0 - fee_pc(d.bid); e0 = np.maximum(b0, s0)
        r0 = np.where(b0 >= s0, d.y - d.ask - fee_pc(d.ask), d.bid - d.y - fee_pc(d.bid))
        o["zero_latency_realized_c"] = {f"ge_{int(th*100)}c": [float(100 * r0[e0 >= th].mean()), int((e0 >= th).sum())] for th in (0.0, 0.02, 0.05)}
        o["mean_abs_model_minus_mid_c"] = float(100 * (d.p - d.mid).abs().mean()); o["mean_fee_at_mid_c"] = float(100 * fee_pc(d.mid).mean())
        o["mean_signed_edge_after_costs_c"] = float(100 * ((d.p - d.mid).abs() - d.spread / 2 - fee_pc(d.mid)).mean())
        for th in (0.0, 0.01, 0.02, 0.03, 0.05):
            x = d[d.edge >= th]
            if len(x) > 20:
                day = x.groupby("date").real.mean()
                o[f"realized_c_edge_ge_{int(th*100)}c"] = {"mean_c": float(100 * x.real.mean()), "rows": int(len(x)), "windows": int(x.wi.nunique()),
                                                          "t_day": float(day.mean() / (day.std(ddof=1) / np.sqrt(len(day))))}
        A = np.full((7, 9), np.nan); S_ = A.copy(); R_ = A.copy(); N_ = np.zeros((7, 9), int); NR = N_.copy()
        for (tb, db), x in d.groupby(["tb", "db"]):
            A[tb, db] = 100 * x.edge.mean(); S_[tb, db] = (x.edge > 0).mean(); N_[tb, db] = x.wi.nunique()
            xx = x[x.edge >= 0.02]
            if xx.wi.nunique() >= 30: R_[tb, db] = 100 * xx.real.mean(); NR[tb, db] = xx.wi.nunique()
        o["grid_edge_vs_quotes_c"] = np.round(A, 2).tolist(); o["grid_share_pos"] = np.round(S_, 3).tolist()
        o["grid_realized_ge2c"] = np.round(R_, 2).tolist(); o["grid_windows"] = N_.tolist(); o["grid_windows_ge2c"] = NR.tolist()
        QG[sp] = (A, R_)
        # post-hoc (not gate-eligible): take 10 contracts at each qualifying minute-end quote, cap 100/window
        o["posthoc"] = {}
        for th in (0.02, 0.03, 0.05, 0.08):
            x = d[d.edge >= th].sort_values(["wi", "sec"]); x = x[x.groupby("wi").cumcount() < 10]
            qpx = np.where(x.dir == 1, x.ask, x.bid); pnlr = 10 * np.where(x.dir == 1, x.y - x.ask, x.bid - x.y) - fee_order(10, qpx)
            pw = pd.Series(pnlr).groupby(x.wi.values).sum(); cw = pd.Series(10.0, index=x.index).groupby(x.wi.values).sum()
            o["posthoc"][f"theta_{int(th*100)}c"] = gate(pw.values, cw.values, W.date.values[pw.index.values])
        OUT[f"quotes_{sp}"] = o
    # does the model add information beyond the mid?  y ~ a*logit(mid) + b*logit(p)
    lg = lambda x: np.log(np.clip(x, 1e-4, 1 - 1e-4) / (1 - np.clip(x, 1e-4, 1 - 1e-4)))
    dtr, dva = Cd[Cd.split == "train"], Cd[Cd.split == "valid"]
    f = lambda th, d: M.logloss(1 / (1 + np.exp(-(th[0] * lg(d.mid.values) + th[1] * lg(d.p.values)))), d.y.values)
    r = optimize.minimize(f, [1.0, 0.0], args=(dtr,), method="Nelder-Mead")
    OUT["encompassing"] = {"w_mid": float(r.x[0]), "w_model": float(r.x[1]), "train_ll_combo": float(r.fun), "train_ll_mid": f([1, 0], dtr), "train_ll_model": f([0, 1], dtr),
                           "valid_ll_combo": f(r.x, dva), "valid_ll_mid": f([1, 0], dva), "valid_ll_model": f([0, 1], dva)}
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if not kk.startswith(("spread_by", "grid"))} for k, v in OUT.items() if k.startswith(("quotes", "encomp"))}, indent=1), flush=True)


import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 3, figsize=(18, 4.8))
panels = [(QG["valid"][0], "A. Apparent edge vs displayed quotes\n(|model - mid| - half-spread - taker fee), cents"),
          (QG["valid"][1], "B. Realised P&L when apparent edge >= 2c\n(buy at ask / sell at bid, after fee), cents"),
          (G_["realized_when_edge_ge2c_valid"], "C. Realised P&L copying tape prints with\nmodel edge >= 2c (1s latency, after fee), cents")]
for a, (A, title) in zip(ax, panels):
    A = np.asarray(A)[::-1]; im = a.imshow(np.ma.masked_invalid(A), cmap="RdBu", vmin=-6, vmax=6, aspect="auto")
    a.set_xticks(range(9)); a.set_xticklabels(BPS_LABELS, rotation=45, ha="right", fontsize=8)
    a.set_yticks(range(7)); a.set_yticklabels(TAU_LABELS[::-1], fontsize=8)
    for i in range(7):
        for j in range(9):
            if np.isfinite(A[i, j]): a.text(j, i, f"{A[i, j]:+.1f}", ha="center", va="center", fontsize=7.5, color="black" if abs(A[i, j]) < 4 else "white")
    a.set_title(title, fontsize=10); a.set_xlabel("expected closing average minus target (bps)"); a.set_ylabel("seconds to close")
    plt.colorbar(im, ax=a, fraction=0.046)
plt.suptitle("KXXRP15M validation (2026-08-01..09-30): edge by seconds remaining and distance from target. Blank = no quotes in the final minute / too few windows.", fontsize=10)
plt.tight_layout(); plt.savefig(os.path.join(ROOT, "figures", "edge_grid.png"), dpi=150); plt.close()

# ---- (E) tape order-flow imbalance (stand-in for book imbalance, which has no history) ----
nW = len(W)
buyv = np.zeros((nW, 900)); sellv = np.zeros((nW, 900))
np.add.at(buyv, (T.wi.values[s == 1], T.sec.values[s == 1]), n[s == 1]); np.add.at(sellv, (T.wi.values[s == -1], T.sec.values[s == -1]), n[s == -1])
cb = np.cumsum(buyv, 1); cs = np.cumsum(sellv, 1)
flow = {}
for L in (30, 60, 120):
    b = cb.copy(); b[:, L:] -= cb[:, :-L]; a = cs.copy(); a[:, L:] -= cs[:, :-L]
    flow[L] = np.where(b + a > 0, (b - a) / np.maximum(b + a, 1e-9), 0.0)
secs = np.arange(60, 890, 15); wi_all = np.repeat(np.arange(nW), len(secs)); ss = np.tile(secs, nW)
zz = C.z[wi_all, ss]; yy = W.yes.values[wi_all].astype(float); tau = 899 - ss; sc = np.asarray(C.par["scale"])[M.tau_bucket(tau)]
spl = W.micro_split.values[wi_all]; dts = W.date.values[wi_all]
def ll_rows(p, yv): p = np.clip(p, 1e-6, 1 - 1e-6); return -(yv * np.log(p) + (1 - yv) * np.log(1 - p))
OUT["flow_signal"] = {}
for L in (30, 60, 120):
    x = flow[L][wi_all, ss]; mt = (spl == "train") & np.isfinite(zz); mv = (spl == "valid") & np.isfinite(zz)
    f = lambda gam: ll_rows(stats.t.cdf(sc[mt] * (zz[mt] + gam[0] * x[mt]), df=C.par["nu"]), yy[mt]).mean()
    r = optimize.minimize(f, [0.0], method="L-BFGS-B"); o = {"gamma": float(r.x[0])}
    for sp, m in (("train", mt), ("valid", mv)):
        d = ll_rows(stats.t.cdf(sc[m] * (zz[m] + r.x[0] * x[m]), df=C.par["nu"]), yy[m]) - ll_rows(stats.t.cdf(sc[m] * zz[m], df=C.par["nu"]), yy[m])
        day = pd.Series(d).groupby(dts[m]).mean(); o[sp] = {"dlogloss": float(d.mean()), "t_day": float(day.mean() / (day.std(ddof=1) / np.sqrt(len(day))))}
    OUT["flow_signal"][f"L{L}"] = o
print("flow", json.dumps(OUT["flow_signal"]), flush=True)

# ---- (F) strategies (pre-registered family; thresholds chosen on train-micro only) ----
CAP = 100.0
def run_taker(Tx, theta, tau_lo=10, tau_hi=890):
    """Copy executable prints whose 1s-stale model edge after fee >= theta. Fill <= printed size, cap 100/window."""
    d = Tx[(Tx.edge >= theta) & (Tx.tauc > tau_lo) & (Tx.tauc <= tau_hi)]
    pnl = np.zeros(nW); cnt = np.zeros(nW)
    wi = d.wi.values; sz = d["count"].values; qq = d.yes_price.values; sd = d.side.values; yv = d.y.values
    start = np.flatnonzero(np.r_[True, wi[1:] != wi[:-1]]); end = np.r_[start[1:], len(wi)]
    for a, b in zip(start, end):
        left = CAP; w = wi[a]
        for k in range(a, b):
            if left <= 0: break
            f = min(sz[k], left); left -= f
            pnl[w] += f * sd[k] * (yv[k] - qq[k]) - fee_order(f, qq[k]); cnt[w] += f
    return pnl, cnt

def tick_floor(x): return np.where((x < 0.1) | (x > 0.9), np.floor(x * 1000 + 1e-9) / 1000, np.floor(x * 100 + 1e-9) / 100)
def tick_ceil(x): return np.where((x < 0.1) | (x >= 0.9), np.ceil(x * 1000 - 1e-9) / 1000, np.ceil(x * 100 - 1e-9) / 100)

def run_maker(Tx, P, theta, hold=10, tau_min=30):
    """Every `hold` s post bid=floor(p-theta), ask=ceil(p+theta); live from t+1..t+hold.
    Filled only when a print trades strictly through the quote. Maker fee 0. Cap 100 contracts/window."""
    pnl = np.zeros(nW); cnt = np.zeros(nW)
    wi = Tx.wi.values; sec = Tx.sec.values; sz = Tx["count"].values; qq = Tx.yes_price.values; sd = Tx.side.values; yv = Tx.y.values
    start = np.flatnonzero(np.r_[True, wi[1:] != wi[:-1]]); end = np.r_[start[1:], len(wi)]
    for a, b in zip(start, end):
        w = wi[a]; left = CAP; se = sec[a:b]
        for t in range(10, 899 - tau_min, hold):
            if left <= 0: break
            p = P[w, t]
            if not np.isfinite(p): continue
            lo = a + np.searchsorted(se, t + 1); hi = a + np.searchsorted(se, t + hold, side="right")
            if hi <= lo: continue
            bid = float(tick_floor(p - theta)); ask = float(tick_ceil(p + theta))
            for k in range(lo, hi):
                if left <= 0: break
                if sd[k] == -1 and qq[k] < bid - 1e-9 and bid > 0:        # someone sold Yes through our bid
                    f = min(sz[k], left); left -= f; pnl[w] += f * (yv[k] - bid); cnt[w] += f
                elif sd[k] == 1 and qq[k] > ask + 1e-9 and ask < 1:       # someone bought Yes through our ask
                    f = min(sz[k], left); left -= f; pnl[w] += f * (ask - yv[k]); cnt[w] += f
    return pnl, cnt

is_tr = (W.micro_split == "train").values; is_va = ~is_tr; dates = W.date.values
def summarize(pnl, cnt, m): return gate(pnl[m], cnt[m], dates[m])
STR = {}
# T1: taker, baseline model
sel = {}
for th in (0.01, 0.02, 0.03, 0.05, 0.08):
    pnl, cnt = run_taker(T, th); sel[th] = (summarize(pnl, cnt, is_tr), pnl, cnt)
    print("T1 train theta", th, {k: v for k, v in sel[th][0].items() if k != "pass"}, flush=True)
ok = {th: v for th, v in sel.items() if v[0]["windows_traded"] >= 300}
best = max(ok, key=lambda th: ok[th][0].get("pnl_per_contract_c", -99))
STR["T1_taker_model"] = {"theta": best, "train_scan": {str(th): v[0] for th, v in sel.items()}, "valid": summarize(sel[best][1], sel[best][2], is_va)}
# T2: taker, model + lead-lag augmentation (gammas from the train fit in results_model.json)
sig = RM["signals"]["leadlag_xrp_perp+btc_perp"]; nmx = [k for k in RM["signals"] if k.startswith("leadlag_xrp_perp_L")][0]; nmb = [k for k in RM["signals"] if k.startswith("leadlag_btc_perp_L")][0]
Lx = int(nmx.split("_L")[1]); Lb = int(nmb.split("_L")[1])
# M1 first (uses the baseline model), then overwrite p/edge in place for T2 to save memory
selm = {}
for th in (0.01, 0.02, 0.03, 0.05):
    pnl, cnt = run_maker(T, C.p, th); selm[th] = (summarize(pnl, cnt, is_tr), pnl, cnt)
    print("M1 train theta", th, {k: v for k, v in selm[th][0].items() if k != "pass"}, flush=True)
ok = {th: v for th, v in selm.items() if v[0]["windows_traded"] >= 300}
bestm = max(ok, key=lambda th: ok[th][0].get("pnl_per_contract_c", -99))
STR["M1_maker_model"] = {"theta": bestm, "train_scan": {str(th): v[0] for th, v in selm.items()}, "valid": summarize(selm[bestm][1], selm[bestm][2], is_va)}
import gc
del buyv, sellv, cb, cs, flow; gc.collect()
C2 = Ctx(extra_gamma={("perp", "XRPUSDT", Lx): sig["gamma"][0], ("perp", "BTCUSDT", Lb): sig["gamma"][1]}, base=C)
T["p"] = C2.p[T.wi.values, T.sec.values - 1]; T["edge"] = T.side * (T.p - T.yes_price) - T.fee
del C2; gc.collect(); T2 = T
sel2 = {}
for th in (0.01, 0.02, 0.03, 0.05, 0.08):
    pnl, cnt = run_taker(T2, th); sel2[th] = (summarize(pnl, cnt, is_tr), pnl, cnt)
    print("T2 train theta", th, {k: v for k, v in sel2[th][0].items() if k != "pass"}, flush=True)
ok = {th: v for th, v in sel2.items() if v[0]["windows_traded"] >= 300}
best2 = max(ok, key=lambda th: ok[th][0].get("pnl_per_contract_c", -99))
STR["T2_taker_model_leadlag"] = {"theta": best2, "lags": {"xrp_perp": Lx, "btc_perp": Lb}, "train_scan": {str(th): v[0] for th, v in sel2.items()}, "valid": summarize(sel2[best2][1], sel2[best2][2], is_va)}
OUT["strategies"] = STR
for k, v in STR.items(): print(k, "theta", v["theta"], "VALID", json.dumps(v["valid"]), flush=True)
json.dump(OUT, open(os.path.join(DATA, "results_market.json"), "w"), indent=1, default=float)
print("saved")
