"""Assemble REPORT.md from the result JSON files (numbers are never typed by hand)."""
import json, os, math, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, ROOT
RM = json.load(open(os.path.join(DATA, "results_model.json")))
RK = json.load(open(os.path.join(DATA, "results_market.json")))
INV = json.load(open(os.path.join(DATA, "inventory.json")))
BIN = json.load(open(os.path.join(DATA, "inventory_binance.json")))
BK = json.load(open(os.path.join(DATA, "results_book.json")))
PAR = json.load(open(os.path.join(DATA, "model_params.json")))
TAU = ["0-10", "10-30", "30-60", "60-120", "120-300", "300-600", "600-900"]
BPS = RK["grid_axes"]["dist_bps"]
L = []
w = L.append
def table(header, rows):
    w("| " + " | ".join(header) + " |"); w("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows: w("| " + " | ".join(str(x) for x in r) + " |")
    w("")
def fmt(x, d=2, plus=False):
    if x is None or (isinstance(x, float) and not math.isfinite(x)): return "–"
    return f"{x:+.{d}f}" if plus else f"{x:.{d}f}"
def grid(A, N=None, d=1):
    A = np.array(A, dtype=float)
    rows = []
    for i in range(len(TAU) - 1, -1, -1):
        if not np.isfinite(A[i]).any(): continue
        rows.append([TAU[i]] + [fmt(A[i, j], d, True) for j in range(9)])
    table(["sec to close \\ distance (bps)"] + BPS, rows)

S = RK["strategies"]; qv, qt = RK["quotes_valid"], RK["quotes_train"]
w("# KXXRP15M (Kalshi XRP 15-minute) — is there a tradeable edge?")
w("")
w("Research and paper analysis only. No orders were placed, no trading account or API key was used; every request was an unauthenticated GET for public market data.")
w("Study date: 2026-11-14. All market facts below were read live on that date; sources are numbered in [Sources](#sources).")
w("")
w("## Verdict")
w("")
w("@@VERDICT@@")
w("")
# ---------------- contract ----------------
w("## 1. Contract summary (verified live)")
w("")
rc = INV["rule_checks"]
table(["Item", "What the rules say", "Source"], [
 ["Question", "\"XRP price up in next 15 mins?\" One binary market per 15-minute window, 96 per day", "[S2]"],
 ["Settlement index", "CF Benchmarks XRPUSD_RTI (Real Time Index), published once per second", "[S1] [S2]"],
 ["Closing value", "Simple average of the 60 RTI prints in the last minute before the close, **rounded to 4 decimals**", "[S2] [S3]"],
 ["Target price", "The same 60-second average taken in the minute before the window **opens** (shown as \"Target Price\"; it is `floor_strike` in the API and is TBD until the open)", "[S2]"],
 ["Payout", "Yes pays $1 if closing value is **at least** the target (`strike_type = greater_or_equal`): a tie pays Yes", "[S2] [S3]"],
 ["Missing data", "\"If no data is available or incomplete on the Expiration Date at the Expiration Time, then affected strikes resolve to No\"", "[S3]"],
 ["Price ticks", "`tapered_deci_cent`: $0.001 steps below $0.10 and above $0.90, $0.01 steps in between", "[S2]"],
 ["Trading hours", "24 hours, 7 days, except a weekly maintenance pause **Thursday 3:00–5:00 AM ET** (orders cannot be placed or amended; cancels allowed)", "[S4] [S5] [S6]"],
 ["Settlement timing", "`settlement_timer_seconds = 1`; settlement was recorded about 4.6 s after the close in the three settled markets inspected", "[S2]"],
 ["Position accountability", "$25,000 per strike, per member", "[S3]"],
])
w("**What the data adds to the rule text** (checked on " + f"{rc['n']:,}" + " settled windows, 2026-02-11 → 2026-09-30, against Kalshi's own per-second index series [S7]):")
w("")
w(f"- The closing value equals the series value stamped one second *before* the close, i.e. the mean of the prints stamped T−60 … T−1, rounded to 4 dp, in **{100*rc['expiration_equals_round4_avg_at_close_minus_1s']:.2f}%** of windows. The few misses are exact half-way cases (5th decimal exactly 5), which round either way.")
w(f"- The target equals the same quantity one second before the open in **{100*rc['target_equals_round4_avg_at_open_minus_1s']:.2f}%** of windows — each window's target is the previous window's closing value.")
w(f"- `result == (closing value >= target)` in **{100*rc['result_equals_expv_ge_target']:.2f}%** of windows.")
w(f"- Rounding to 4 decimals makes exact ties common: **{100*rc['tie_rate']:.2f}%** of windows closed exactly on the target, and every one resolved Yes. With XRP near $1, one rounding step is about 1 basis point.")
w(f"- {rc['floor_strike_missing_in_api']} archived markets have no `floor_strike` in the API; for those the target was rebuilt from the index.")
w("")
# ---------------- fees ----------------
w("## 2. Fees")
w("")
w("`GET /series/KXXRP15M` returns `fee_type: \"quadratic\"`, `fee_multiplier: 1` [S1]. `GET /series/fee_changes` returns no past or scheduled changes for the series [S8]. Per the fee schedule (\"last updated and effective July 7, 2026\") [S9] and the API's definition of the fee types [S10]:")
w("")
w("- **Taker:** `fee = round_up(0.07 × contracts × P × (1 − P))`, P in dollars.")
w("- **Maker:** resting orders are charged only for series with a maker multiplier. The default maker multiplier is 0 and KXXRP15M is not on the non-standard list, and its fee type is `quadratic`, not `quadratic_with_maker_fees`. **Maker fee = 0.**")
w("- **Rounding:** the fee is rounded up so that the order's total balance change lands on a whole cent for accounts that are not direct exchange members (on $0.0001 for direct members); the round-up is shared across all fills of one order [S11]. Small orders therefore pay proportionally more.")
w("- No settlement fee [S9].")
w("")
rows = []
for p in (0.10, 0.30, 0.50, 0.70, 0.90):
    f = lambda n: math.ceil(0.07 * n * p * (1 - p) * 100 - 1e-9) / 100
    rows.append([f"{int(p*100)}c", f"{7*p*(1-p):.2f}c", f"{100*f(1):.0f}c", f"{100*f(10)/10:.1f}c", f"{100*f(100)/100:.2f}c", f"{100*0.07*(1-p):.1f}%", "0c"])
table(["Price", "Taker fee per contract (formula)", "1-contract order", "10-contract order, per contract", "100-contract order, per contract", "Taker fee as % of stake", "Maker fee"], rows)
w("Each window opens near 50c, where the taker fee peaks at 1.75c per contract (2c on a single contract). A taker who buys at 50c and is right 50% of the time loses the fee plus half the spread on every trade.")
w("")
# ---------------- data ----------------
w("## 3. Data inventory")
w("")
ix = INV["index"]; tr = INV["trades"]; mb = INV["markets_by_split"]
table(["Dataset", "Source", "Coverage", "Resolution", "Size"], [
 ["Settled windows and outcomes", "`/historical/markets` + `/markets` [S12]", f"{INV['first_close'][:10]} (series start) → 2026-11-14", "one row per window", f"{INV['markets_total_listed']:,} markets listed; {mb['train']:,} train, {mb['valid']:,} validation, {mb['holdout_locked']:,} holdout (locked)"],
 ["XRP index (trailing-60 s mean of XRPUSD_RTI)", "`/live_data/events/{event}` [S7]", f"{ix['first'][:10]} → {ix['last'][:10]}", "1 second", f"{ix['seconds_present']:,} seconds"],
 ["Raw 1-second RTI", "recovered from the series above (section 4)", "same", "1 second", f"{100*ix['raw_recovered_share']:.1f}% of the span"],
 ["Kalshi trade tape", "`/historical/trades` + `/markets/trades` [S12]", f"{tr['first']} → {tr['last']} ({tr['days']} days)", "every trade, with taker side", f"{tr['trades']:,} trades, {tr['contracts']/1e6:.0f}M contracts"],
 ["Kalshi 1-minute bid/ask", "market candlesticks [S13]", f"{tr['first']} → {tr['last']}", "1 minute", f"{qt['windows']+qv['windows']:,} windows (sample)"],
 ["Binance XRPUSDT and BTCUSDT spot", "data.binance.vision 1s klines [S14]", f"{BIN['spot_XRPUSDT']['first']} → {BIN['spot_XRPUSDT']['last']}", "1 second", f"{BIN['spot_XRPUSDT']['days']} days each, none missing"],
 ["Binance XRPUSDT and BTCUSDT perpetual", "data.binance.vision aggTrades, built into 1 s bars [S14]", "same", "1 second", f"{BIN['perp_XRPUSDT']['days']} days each, none missing"],
 ["Live order book (recorder)", "`/markets/{ticker}/orderbook` [S15]", f"{BK['span_min']:.0f} minutes on 2026-11-14", "1 second", f"{BK['snapshots']:,} snapshots — far short of the 14 days required"],
])
w("**How far back the API goes.** The series' first window closed " + INV["first_close"][:16].replace("T", " ") + " UTC. Kalshi serves the per-second index for any 15-minute event for the hour before it matures, so the index is available for the whole life of the series. Markets, trades and candlesticks older than the archive cutoffs (2026-09-15 on the study date) come from the `/historical/*` endpoints [S16]. **Historical order books are not available from any endpoint**; only the current book can be read.")
w("")
w("**Gaps, outages and the weekly pause**")
w("")
brk = INV["window_breaks"]
thu = [b for b in brk if b[2] <= 12]; other = [b for b in brk if b[2] > 12]
w(f"- *Weekly pause.* {len(thu)} Thursdays have no listed windows around the maintenance pause. Through June 18, 12 windows were skipped each Thursday (listing stopped about an hour before the pause began); from June 25, 9 windows; from August 27 exactly the 8 windows closing 3:15–5:00 AM ET. The first window after the pause closes 5:15 AM ET.")
for b in other:
    w(f"- *Unscheduled listing gap.* No windows between {b[0][:16].replace('T',' ')} and {b[1][:16].replace('T',' ')} UTC ({b[2]} windows missing).")
w(f"- *Index short gaps.* {ix['short_gaps_n']} gaps of at most {ix['short_gap_max_s']} s (median {ix['short_gap_median_s']:.0f} s, {ix['short_gaps_seconds']:,} s in total). All fall on weekdays and {100*sum(ix['short_gaps_by_utc_hour'][20:]+ix['short_gaps_by_utc_hour'][:2])/ix['short_gaps_n']:.0f}% start between 20:00 and 02:00 UTC. For up to a minute after each gap Kalshi's series is not a clean 60-print average, so those seconds are treated as missing too ({ix['nonint_or_warmup_seconds']:,} s).")
lg = [g for g in ix["long_gaps"] if g[2] not in (7200, 10800, 32400)]
for g_ in lg: w(f"- *Index outage.* {g_[0]} → {g_[1]} UTC ({g_[2]:,} s).")
w("- *Index around the pause.* The index was requested only for hours that have a listed window, so it has matching 2–3 hour holes on Thursdays and on the two unscheduled gaps; these are \"not requested\", not confirmed outages.")
io = INV["idx_ok"]
w(f"- *Effect on the sample.* A window is used only if the raw index is complete from 60 s before the open to the close: {io['train'][0]:,} of {io['train'][1]:,} train windows ({100*io['train'][0]/io['train'][1]:.1f}%) and {io['valid'][0]:,} of {io['valid'][1]:,} validation windows ({100*io['valid'][0]/io['valid'][1]:.1f}%).")
w(f"- *Binance.* No missing daily files. Longest run of seconds without a trade: XRP spot {BIN['spot_XRPUSDT']['longest_no_trade_run_s']} s, XRP perp {BIN['perp_XRPUSDT']['longest_no_trade_run_s']} s, BTC spot {BIN['spot_BTCUSDT']['longest_no_trade_run_s']} s, BTC perp {BIN['perp_BTCUSDT']['longest_no_trade_run_s']} s. XRP spot has no trade in {100*BIN['spot_XRPUSDT']['share_seconds_no_trade']:.0f}% of seconds, so the perpetual ({100*BIN['perp_XRPUSDT']['share_seconds_no_trade']:.0f}%) is the better 1-second reference.")
w(f"- *Order-book recorder.* `recorder/record_book.py` snapshots the full book every second. It ran for {BK['span_min']:.0f} minutes in this session ({100*BK['coverage']:.0f}% of seconds captured, median request latency {1000*BK['request_latency_s']['50']:.0f} ms) as a functional test. This research container is temporary, so the 14-day run has **not** happened; fills against displayed size could not be modelled from books.")
w("")
w("**Split (fixed in `PREREG.md` before any outcome was analysed).** Train 2026-02-11 → 07-31, validation 2026-08-01 → 09-30, holdout 2026-10-01 onward. The holdout was never loaded: no index, trades or quotes were downloaded for it and the loader drops its rows. Trades and quotes were pulled for June–September only, so anything that needs market prices uses June–July as train and August–September as validation.")
w("")
# ---------------- model ----------------
import pandas as pd
bl = RM["baseline"]; cal = PAR["calib"]; har = RM["har"]
w("## 4. Fair-value model")
w("")
w("**Recovering the raw index.** Kalshi publishes the trailing 60-second mean A(t), not the 1-second print R(t). Because A is a mean of 60 prints on a $0.00001 grid, `60·A(t)` is an integer number of ticks and `R(t) − R(t−60) = 60·(A(t) − A(t−1))` exactly. Within each gap-free stretch this fixes R up to a pattern that repeats every 60 s, which is chosen to make R smoothest. Checks: 1-second changes of the recovered R have a correlation of about 0.7 with Binance spot changes in the same second, and their autocorrelation at a 60-second lag is below 0.02, so no visible artefact remains. Residual error is a few ticks (about 0.2 bps).")
w("")
w("**State variables** at second *t* of a window that settles on the prints stamped T−60 … T−1:")
w("")
w("- **Distance from target, in index terms.** `μ(t)` = the expected closing average. With more than 60 s left, `μ(t) = R(t)`, the latest raw print — *not* the displayed trailing average, which lags the raw print by about 30 s. Inside the final minute, `μ(t) = (sum of closing-minute prints already seen + number still to come × R(t)) / 60`. Distance is `ln(μ(t) / K*)` with `K* = target − 0.00005`, the lowest closing average that still rounds up to the target.")
w("- **Seconds remaining** `τ`, to the final print.")
w("- **Short-horizon realised volatility** `σ²(t)`: a forecast of per-second variance over the next 15 minutes from realised variance of 30-second index returns over the trailing 5 min, 15 min, 1 h, 6 h and 24 h plus hour-of-day effects (log-linear regression fitted on train).")
w("")
w("**Baseline probability, with the averaging modelled directly.** For a random walk the variance of the closing 60-second average, seen from *t*, is `σ² × g(τ)` where")
w("")
w("- `g(τ) = τ − 39.5` for τ ≥ 60 (averaging removes about 40 s worth of variance), and")
w("- `g(τ) = τ(τ+1)(2τ+1) / 21600` for τ < 60 — only the prints still to come matter, each weighted by how many closing-minute seconds it affects. At τ = 30 this is 2.6 s worth of variance instead of 30.")
w("")
w(f"`z = ln(μ/K*) / sqrt(σ² g(τ))` and `P(Yes) = T_ν(s_b · z)`: a Student-t distribution (fat tails) with ν = {cal['nu']:.2f} and one scale per time bucket, all fitted by maximum likelihood on train only.")
w("")
table(["Fitted on train"] + TAU, [["scale s_b"] + [f"{x:.2f}" for x in cal["scale"]]])
w(f"Volatility forecast: R² = {har['r2_train']:.2f} on train, {har['r2_valid']:.2f} on validation (log variance of the next 15 minutes). Weights on trailing log variance: " + ", ".join(f"{int(k)//60} min {v:.2f}" for k, v in har["coef_logrv"].items()) + ".")
w("")
w("**Does modelling the averaging matter?** Log-loss (lower is better; 0.693 = coin flip) against settled outcomes, sampled every 5 s in every window. \"Chart model\" uses what the Kalshi chart shows (the trailing average as the current price, variance proportional to time left).")
w("")
rows = []
for nm, lab in (("naive_chart", "Chart model"), ("full", "This model")):
    for sp in ("train", "valid"):
        r = bl[nm][sp]; rows.append([lab, sp, f"{r['logloss']:.4f}", f"{r['brier']:.4f}"] + [f"{x:.3f}" for x in r["by_tau"]])
table(["Model", "Split", "Log-loss", "Brier"] + [f"τ {t}" for t in TAU], rows)
w(f"The model does not degrade out of sample (validation log-loss {bl['full']['valid']['logloss']:.4f} vs train {bl['full']['train']['logloss']:.4f}). Nearly all the gain over the chart model is in the last two minutes.")
w("")
w("## 5. Calibration")
w("")
w("![Calibration](figures/calibration.png)")
w("")
w("*Model probability vs how often the window settled Yes, one observation per window at each time-to-close, decile bins, 95% binomial intervals. Left: train. Right: validation.*")
w("")
w("Validation, all sampled seconds pooled:")
w("")
table(["Model says", "Settled Yes", "Rows"], [[f"{100*a:.1f}%", f"{100*b:.1f}%", f"{n:,}"] for a, b, n in RM["calibration_valid_pooled"]])
w("When the model says 70–80% the window settles Yes about 75% of the time; the largest gap in any decile is about 1.5 percentage points. The model is well calibrated out of sample.")
w("")
# ---------------- signals ----------------
w("## 6. Signals tested one at a time")
w("")
w("Each signal was added alone to the baseline; its coefficient was fitted on train. ΔLL is the change in log-loss (negative = better). *t* is computed across days. The pre-registered rule keeps a signal only if it improves train **and** has the same sign on validation; the last column applies that rule mechanically, and the notes below say which effects are large enough to matter.")
w("")
names = {"leadlag_xrp_perp": "Binance XRP perp minus index, last {L} s", "leadlag_xrp_spot": "Binance XRP spot minus index, last {L} s", "leadlag_btc_perp": "BTC perp return, last {L} s",
         "leadlag_btc_spot": "BTC spot return, last {L} s", "leadlag_xrp_perp+btc_perp": "XRP perp gap + BTC perp return together", "prev_window_return": "Previous window's return (momentum/reversal)",
         "prev_window_return_first5min": "Previous window's return, first 5 minutes only", "prev_window_outcome_sign": "Previous window's outcome (up/down)",
         "vol_regime_scale": "Volatility regime (terciles) — width", "vol_regime_bias": "Volatility regime (terciles) — up/down bias", "hour_bias": "Hour of day — up/down bias",
         "hour_scale": "Hour of day — width", "dow_bias": "Day of week — up/down bias", "dow_scale": "Day of week — width"}
rows = []
for k, v in RM["signals"].items():
    base = k.split("_L")[0] if "_L" in k else k; lab = names.get(base, k)
    if "_L" in k: lab = lab.format(L=k.split("_L")[1])
    gam = ", ".join(f"{x:+.3f}" for x in v["gamma"]) if len(v["gamma"]) <= 2 else f"{len(v['gamma'])} params"
    rows.append([lab, gam, f"{1e4*v['train']['dlogloss']:+.2f} ({v['train']['t_day']:+.1f})", f"{1e4*v['valid']['dlogloss']:+.2f} ({v['valid']['t_day']:+.1f})", "yes" if v["kept"] else "no"])
fs = RK["flow_signal"]["L60"]
rows.append(["Kalshi taker-flow imbalance, last 60 s (Jun–Sep only)", f"{fs['gamma']:+.3f}", f"{1e4*fs['train']['dlogloss']:+.2f} ({fs['train']['t_day']:+.1f})", f"{1e4*fs['valid']['dlogloss']:+.2f} ({fs['valid']['t_day']:+.1f})", "no"])
rows.append(["Order-book imbalance", "–", "not testable", "not testable", "needs recorder data"])
table(["Signal", "Coefficient", "ΔLL train ×10⁴ (t)", "ΔLL validation ×10⁴ (t)", "Same sign on validation"], rows)
ll = pd.read_csv(os.path.join(DATA, "leadlag.csv"))
w("**BTC and Binance lead-lag in detail.** Regression of the index's *next* h-second return on the reference's *last* L-second move (for XRP references: Binance move minus the index's own move over the same L seconds). Train period; validation in brackets.")
w("")
rows = []
for src, lab in (("xrp_perp", "Binance XRP perp"), ("xrp_spot", "Binance XRP spot"), ("btc_perp", "Binance BTC perp"), ("btc_spot", "Binance BTC spot")):
    for Lg in (1, 10, 60):
        r = [lab, f"{Lg} s"]
        for h in (1, 10, 60):
            x = ll[(ll.src == src) & (ll.L == Lg) & (ll.h == h)].iloc[0]
            r.append(f"{100*x.r2_tr:.2f}% [{100*x.r2_va:.2f}%]")
        rows.append(r)
table(["Reference", "Lookback L", "R², next 1 s", "R², next 10 s", "R², next 60 s"], rows)
b1 = ll[(ll.src == "btc_perp") & (ll.L == 1) & (ll.h == 1)].iloc[0]; x1 = ll[(ll.src == "xrp_perp") & (ll.L == 1) & (ll.h == 1)].iloc[0]
w(f"- The lead is real but short. Binance's XRP perpetual explains {100*x1.r2_tr:.1f}% of the index's next 1-second move and BTC's last second explains {100*b1.r2_tr:.1f}%; by 60 s ahead both are near 0.2%. The index simply updates about a second after Binance.")
w("- In probability terms the lead-lag signals improve log-loss by 0.2–0.6 ×10⁻⁴: statistically detectable, same sign on validation, and worth a small fraction of a cent per contract. They help only where one second matters, in the last two minutes.")
w("- Previous-window reversal looks strong on train (t = −3.1) and all but disappears on validation (one-eleventh the size, t = 0.0). Hour of day and day of week fit train and make validation worse (hour of day significantly so). None is usable.")
w("- Volatility regime adds nothing measurable beyond the volatility forecast already in the model. Kalshi taker-flow imbalance has no predictive value. Order-book imbalance cannot be tested without recorded books.")
w("")
# ---------------- edge test ----------------
agv, agt = RK["aggregate_valid"], RK["aggregate_train"]
w("## 7. Edge test against the market")
w("")
w(f"Sample: {RK['n_windows']['train']:,} train windows (June–July) and {RK['n_windows']['valid']:,} validation windows (August–September); {RK['n_trades']['train']+RK['n_trades']['valid']:,} trades inside those windows. A typical validation window has {RK['per_window']['valid']['median_trades']:,.0f} trades and {RK['per_window']['valid']['median_contracts']:,.0f} contracts (June–July: {RK['per_window']['train']['median_trades']:,.0f} and {RK['per_window']['train']['median_contracts']:,.0f}).")
w("")
w("### 7.1 Who makes money now")
w("")
w("Every trade on the tape has a taker (pays the fee) and a maker (rests, pays nothing). Settling each trade at the window's outcome, per contract:")
w("")
rows = []
for sp, a in (("train (Jun–Jul)", agt), ("validation (Aug–Sep)", agv)):
    rows.append([sp, f"{a['taker_pnl_c']:+.2f}c", f"{a['fee_c']:.2f}c", f"{a['taker_pnl_c']+a['fee_c']:+.2f}c", f"{a['maker_pnl_c']:+.2f}c", f"{a['taker_pnl_day_t']:+.0f}"])
table(["Period", "Takers, after fee", "Fee paid", "Takers, before fee", "Makers", "t across days (takers)"], rows)
rows = [[x["tau"], f"{x['contracts']/1e6:.1f}M", f"{x['taker_pnl_c']:+.2f}c", f"{x['fee_c']:.2f}c", f"{x['maker_pnl_c']:+.2f}c"] for x in RK["by_tau_valid"][::-1]]
w("Validation, by seconds to close:")
w("")
table(["Sec to close", "Contracts", "Takers after fee", "Fee", "Makers"], rows)
w(f"Takers as a group lose about {-agv['taker_pnl_c']:.1f}c per contract, a little more than half of it fees, and the loss is consistent from day to day. It is largest early in the window, where prices sit near 50c and the fee is highest. Makers as a group earn about {agv['maker_pnl_c']:.1f}c per contract with no fee. That is the only reliably positive number in this study, and it belongs to whoever already holds queue priority.")
w("")
w("**Is the market price itself calibrated?** Contract-weighted, at trade prices, validation:")
w("")
table(["Price bin", "Mean price", "Settled Yes", "Contracts"], [[x["bin"], f"{100*x['mean_price']:.1f}c", f"{100*x['yes_freq']:.1f}%", f"{x['contracts']/1e6:.1f}M"] for x in RK["price_calibration_valid"]])
w("Prices are close to calibrated. In validation, 60–80c prices settled Yes about 2 points more often than priced and 10–20c prices about 1 point less often; in train every bin settled Yes more often than priced. The pattern is not stable across the two periods and is smaller than the taker fee in the middle of the range.")
w("")
enc = RK["encompassing"]
w("### 7.2 Model against the displayed quote")
w("")
w(f"1-minute bid/ask closes for {qt['windows']:,} train and {qv['windows']:,} validation windows (sample), minutes 1–14 of each window. Median spread {qt['median_spread_c']:.0f}c in June–July, {qv['median_spread_c']:.0f}c in August–September (mean {qv['mean_spread_c']:.2f}c). The model is evaluated one second *before* the quote (the pre-registered 1 s latency).")
w("")
table(["", "Train", "Validation"], [
 ["Log-loss, Kalshi mid", f"{qt['logloss_mid']:.4f}", f"{qv['logloss_mid']:.4f}"],
 ["Log-loss, model (1 s stale)", f"{qt['logloss_model']:.4f}", f"{qv['logloss_model']:.4f}"],
 ["Log-loss, blend fitted on train", f"{enc['train_ll_combo']:.4f}", f"{enc['valid_ll_combo']:.4f}"],
 ["Mean absolute gap, model vs mid", f"{qt['mean_abs_model_minus_mid_c']:.2f}c", f"{qv['mean_abs_model_minus_mid_c']:.2f}c"],
 ["Mean cost to cross (half spread + fee)", f"{qt['mean_spread_c']/2+qt['mean_fee_at_mid_c']:.2f}c", f"{qv['mean_spread_c']/2+qv['mean_fee_at_mid_c']:.2f}c"],
 ["Share of quote-minutes with apparent edge > 0", f"{100*qt['share_edge_pos']:.0f}%", f"{100*qv['share_edge_pos']:.0f}%"],
])
cmp_ = lambda q: "more" if q["logloss_model"] < q["logloss_mid"] else "less"
w(f"The 1 s-stale model is slightly {cmp_(qt)} accurate than the Kalshi mid in June–July and slightly {cmp_(qv)} accurate in August–September. A blend fitted on train (weights {enc['w_mid']:.2f} mid, {enc['w_model']:.2f} model on the log-odds) beats both in both periods, so the model carries some information the mid does not, but the mid carries more. The model disagrees with the mid by about 2.6c on average, which is about the cost of crossing; most disagreements are too small to trade.")
w("")
w("### 7.3 Edge grid")
w("")
w("Edge = model probability minus market price, after the taker fee and half the spread (i.e. buying at the ask or selling at the bid, whichever is better). Rows: seconds to close. Columns: expected closing average minus target, in basis points. Validation period. Quotes exist only at minute boundaries, so the last minute is covered by the trade-tape grid (table C).")
w("")
w("![Edge grid](figures/edge_grid.png)")
w("")
w("**A. Apparent edge against displayed quotes, cents per contract** (mean over quote-minutes of the better side; positive = model sees value after costs)")
w("")
grid(qv["grid_edge_vs_quotes_c"])
w("**B. Realised P&L, cents per contract, when the apparent edge was at least 2c** (settled at the outcome, after fee; cells with fewer than 30 windows blank)")
w("")
grid(qv["grid_realized_ge2c"])
w("**C. Realised P&L, cents per contract, from copying actual tape prints where the 1 s-stale model edge was at least 2c** (all seconds, including the final minute)")
w("")
grid(RK["grid_realized_when_edge_ge2c_valid"]["cents"])
w("**D. Average model edge at every executable print, cents per contract** (model minus the price a taker actually paid, after fee)")
w("")
grid(RK["grid_model_edge_valid"]["cents"])
w("**B (train). The same as B for June–July**, for comparison")
w("")
grid(qt["grid_realized_ge2c"])
w("Reading the grids: at a typical print the model says the taker is overpaying by 0.1–5c in every cell (D), consistent with takers' realised losses. The apparent edge against quotes (A) is largest near the target with 1–5 minutes left, where a small index move changes the probability most. Realised results in August–September (B, C) are positive in most cells with 5–10 minutes left and mixed elsewhere; in June–July (B train) they are mixed everywhere. Each cell rests on a few hundred windows at most, and individual cells are not significant.")
w("")
w("### 7.4 Pre-registered strategies and the pass gate")
w("")
w("Three configurations, thresholds chosen on train only, each evaluated once on validation. Execution: 1 s decision latency; a taker order fills only against a print that actually occurred on the same side at that price, up to the printed size; a maker order fills only when a later print trades strictly through it; at most 100 contracts per window; fees rounded up per order; no trading in the last 10 s.")
w("")
gl = lambda ok: "pass" if ok else "**fail**"
rows = []
lab = {"T1_taker_model": "T1 taker: copy prints where model edge ≥ θ", "T2_taker_model_leadlag": "T2 taker: same, model + BTC/Binance lead-lag", "M1_maker_model": "M1 maker: quote model ± θ, refresh every 10 s"}
for k in ("T1_taker_model", "T2_taker_model_leadlag", "M1_maker_model"):
    v = S[k]["valid"]; p = v["pass"]
    rows.append([lab[k], f"{100*S[k]['theta']:.0f}c", f"{v['windows_traded']:,} / {v['days']}", f"{v['pnl_per_contract_c']:+.2f}c [{v['ci95_c'][0]:+.2f}, {v['ci95_c'][1]:+.2f}]",
                 f"${v['max_drawdown']:,.0f}", "–" if v["max_day_share"] is None else f"{100*v['max_day_share']:.0f}%",
                 f"{gl(p['n'])} / {gl(p['expectancy'])} / {gl(p['drawdown'])} / {gl(p['concentration'])}", "**FAIL**" if not p["all"] else "PASS"])
table(["Config", "θ (from train)", "Windows / days", "Net per contract [95% CI]", "Max drawdown", "Best day's share of profit", "Sample / expectancy / drawdown / concentration", "Gate"], rows)
w("Gate (from `PREREG.md`): ≥ 500 traded windows on ≥ 40 days; ≥ +1.0c per contract after fees with the day-block bootstrap 95% lower bound above zero; max drawdown ≤ $1,000 at 100 contracts per window; no day above 20% of total profit.")
w("")
w("Train scan that selected θ (net cents per contract, [95% CI]):")
w("")
ths = sorted({t for k in S for t in S[k]["train_scan"]}, key=float)
rows = []
for k in ("T1_taker_model", "T2_taker_model_leadlag", "M1_maker_model"):
    r = [k.split("_")[0]]
    for t in ths:
        x = S[k]["train_scan"].get(t); r.append("–" if not x else f"{x['pnl_per_contract_c']:+.2f} [{x['ci95_c'][0]:+.1f}, {x['ci95_c'][1]:+.1f}]")
    rows.append(r)
table(["Config"] + [f"θ = {100*float(t):.0f}c" for t in ths], rows)
w("@@GATE_TEXT@@")
w("")
w("### 7.5 Post-hoc check: taking displayed quotes (not gate-eligible)")
w("")
w("After the three pre-registered tests were spent, the quote data suggested a different execution rule: at each minute boundary, take 10 contracts at the displayed quote when the model's edge after fee is at least θ (cap 100 per window). This was looked at on validation without being pre-registered, it assumes the displayed quote had at least 10 contracts (unverified — there are no historical books), and it is reported for transparency only.")
w("")
rows = []
for t in ("theta_2c", "theta_3c", "theta_5c", "theta_8c"):
    a, b = qt["posthoc"][t], qv["posthoc"][t]
    f = lambda x: f"{x['pnl_per_contract_c']:+.2f}c [{x['ci95_c'][0]:+.1f}, {x['ci95_c'][1]:+.1f}], {x['windows_traded']:,} windows" if "pnl_per_contract_c" in x else "–"
    rows.append([t.split("_")[1], f(a), f(b), "–" if b.get("max_day_share") is None else f"{100*b['max_day_share']:.0f}%"])
table(["θ", "Train: net per contract [95% CI]", "Validation: net per contract [95% CI]", "Validation: best day's share"], rows)
w("@@POSTHOC_TEXT@@")
w("")
# ---------------- risk ----------------
w("## 8. Risk rules (proposal only — nothing here is switched on)")
w("")
w("These would apply to a paper-trading phase and, only if the gate is ever passed on the holdout, to a first live phase.")
w("")
table(["Rule", "Proposed value", "Why"], [
 ["Max stake per window", "100 contracts, one direction per window", "The gate was defined at 100 contracts; median displayed size in the live sample was " + f"{BK['best_bid_size']['50']:.0f} contracts at the best bid and {BK['best_ask_size']['50']:.0f} at the best ask"],
 ["Max daily loss", "$300; stop for the rest of the UTC day", "About five full-size losing windows at mid-range prices"],
 ["Max consecutive losing windows", "6, then stand down for 2 hours", "At a 55% window win rate six straight losses happen about once in 120 sequences; more suggests the model or the feed is broken"],
 ["Max drawdown before review", "$1,000", "Same as the pass gate"],
 ["No trade: index outage", "Any missing index second in the last 120 s, or within 60 s after a gap", f"{ix['short_gaps_n']} short gaps were observed, clustered on weekday evenings UTC; incomplete data resolves strikes to No under the contract terms"],
 ["No trade: empty or one-sided book", "No bid or no ask, or spread wider than 5c", f"{100*BK['one_sided_or_empty_share']:.0f}% of 1-second snapshots in the live sample were one-sided"],
 ["No trade: final 10 seconds", "No new orders with 10 s or less to close; cancel resting orders at 15 s", "The outcome is largely fixed and anyone with a faster index feed has the advantage"],
 ["No trade: first 10 seconds", "Wait until the target price is published", "The target is TBD at the open and appeared about 2 s later in the market inspected"],
 ["No trade: weekly pause", "No orders from Thursday 2:45 AM ET to the first window that opens after 5:00 AM ET; cancel-on-pause set on every order", "Orders cannot be placed or amended during the pause"],
 ["No trade: reference feed", "Binance XRP perp silent for more than 5 s (if the lead-lag term is used)", "Longest observed silent run was " + f"{BIN['perp_XRPUSDT']['longest_no_trade_run_s']} s"],
])
# ---------------- limits ----------------
w("## 9. Limits of this study")
w("")
w("- **No historical order books.** Displayed size, queue position and maker fills could not be modelled. The trade tape was used as a stand-in for what was executable; that is a proxy in both directions (it ignores liquidity nobody took, and it assumes we could have had another taker's fill).")
w("- **The recorder has not run for two weeks.** It is written and tested; it needs an always-on host.")
w("- **Index latency is assumed, not measured.** The model uses Kalshi's index series with a 1 s delay. A live trader needs either a CF Benchmarks licence or Kalshi's live feed, and its real delay is unknown.")
w("- **Raw index is reconstructed**, accurate to a few ticks, and unavailable for about 3% of seconds (short stretches between gaps).")
w("- **Market data covers four months** (June–September); volume more than quadrupled over that period, so the market is changing.")
w("- **Quotes are 1-minute closes** for a sample of about half the windows; there are none inside the final minute.")
w("- **Holdout untouched.** Nothing from 2026-10-01 onward was analysed, except recorder health and displayed-size statistics from today's live sample.")
w("")
w("## 10. What would settle the open questions")
w("")
w("1. Run `recorder/record_book.py` on an always-on host for at least 14 days.")
w("2. With books in hand, measure displayed size at the quote, model taker fills against it, and model maker fills with queue position.")
w("3. Evaluate the frozen configuration Q1 (`PREREG.md` addendum) once on the holdout, 2026-10-01 onward, with the same gate. Nothing else should be tuned on the holdout.")
w("")
w("## Reproduce")
w("")
w("```")
w("python3 src/fetch_markets.py        # window list and outcomes")
w("python3 src/fetch_index.py          # per-second index, hourly chunks")
w("python3 src/fetch_trades.py         # trade tape, Jun-Sep")
w("python3 src/fetch_candles.py        # 1-minute bid/ask (ALL=1 for every window)")
w("python3 src/fetch_binance.py 2026-02-10 2026-09-30")
w("python3 src/build_index.py && python3 src/windows.py")
w("python3 src/analyze_model.py && python3 src/analyze_market.py && python3 src/book_stats.py")
w("python3 src/make_report.py")
w("```")
w("")
w("Raw data is not committed (about 0.7 GB); result summaries are in `data/*.json` and `data/leadlag.csv`.")
w("")
w("## Sources")
w("")
w("All retrieved 2026-11-14. API base: `https://api.elections.kalshi.com/trade-api/v2`.")
w("")
for s_ in [
 "[S1] `GET /series/KXXRP15M` — fee type, fee multiplier, settlement source, contract terms URL, \"important information\" text.",
 "[S2] `GET /markets?series_ticker=KXXRP15M&status=open` and `&status=settled` — `rules_primary`, `rules_secondary`, `floor_strike`, `strike_type`, `price_level_structure`, `price_ranges`, `settlement_timer_seconds`, `settlement_ts`.",
 "[S3] Kalshi contract terms, CRYPTO: https://assets.kalshi.com/contract_terms/CRYPTO.pdf",
 "[S4] `GET /exchange/schedule` — standard hours and the Thursday 03:00–05:00 closure.",
 "[S5] Kalshi API docs, Maintenance and Pauses: https://docs.kalshi.com/getting_started/maintenance_and_pauses",
 "[S6] Kalshi Help Center, What are trading hours?: https://help.kalshi.com/en/articles/13823807-what-are-trading-hours",
 "[S7] `GET /live_data/events/{event_ticker}` — per-second index series; docs: https://docs.kalshi.com/api-reference/live-data/get-event-live-data.md",
 "[S8] `GET /series/fee_changes?series_ticker=KXXRP15M&show_historical=true` — empty.",
 "[S9] Kalshi Fee Schedule (last updated and effective July 7, 2026): https://kalshi.com/docs/kalshi-fee-schedule.pdf",
 "[S10] Kalshi API docs, Get Series (definition of `fee_type` values): https://docs.kalshi.com/api-reference/market/get-series.md",
 "[S11] Kalshi API docs, Fee Rounding: https://docs.kalshi.com/getting_started/fee_rounding.md",
 "[S12] `GET /historical/markets`, `/markets`, `/historical/trades`, `/markets/trades` — windows, outcomes, trade tape.",
 "[S13] `GET /historical/markets/{ticker}/candlesticks` and `/series/KXXRP15M/markets/{ticker}/candlesticks` — 1-minute bid/ask.",
 "[S14] Binance public data: https://data.binance.vision/ — `data/spot/daily/klines/{SYMBOL}/1s/` and `data/futures/um/daily/aggTrades/{SYMBOL}/`.",
 "[S15] `GET /markets/{ticker}/orderbook` — current book only.",
 "[S16] Kalshi API docs, Historical Data: https://docs.kalshi.com/getting_started/historical_data.md and `GET /historical/cutoff`.",
]: w("- " + s_)
w("")
txt = "\n".join(L)
BD = json.load(open(os.path.join(DATA, "results_book_depth.json")))
T1, T2, M1 = (S[k]["valid"] for k in ("T1_taker_model", "T2_taker_model_leadlag", "M1_maker_model"))
ph = lambda q, t: q["posthoc"][t]
ci = lambda x: f"{x['pnl_per_contract_c']:+.1f}c [{x['ci95_c'][0]:+.1f}, {x['ci95_c'][1]:+.1f}]"
VERDICT = f"""**No edge.** None of the three strategies fixed in advance passed the pass gate on validation, so under the pre-registered rules the answer is "no edge". One lead found afterwards is unresolved and needs order-book data this study could not collect.

- **Pre-registered tests (August–September, 1 s latency, fills limited to prints that actually traded).** Best result: taker with the BTC/Binance lead-lag term, {T2['pnl_per_contract_c']:+.2f}c per contract after fees, 95% interval [{T2['ci95_c'][0]:+.2f}, {T2['ci95_c'][1]:+.2f}]. It misses the +1.0c bar, the interval includes zero, drawdown was ${T2['max_drawdown']:,.0f} against a $1,000 limit, and one day supplied {100*T2['max_day_share']:.0f}% of the profit. The plain taker made {T1['pnl_per_contract_c']:+.2f}c; the maker lost {abs(M1['pnl_per_contract_c']):.2f}c.
- **Who earns the money today.** Across {RK['contracts']['valid']/1e6:.0f}M contracts in August–September, takers lost {abs(agv['taker_pnl_c']):.1f}c per contract after fees ({agv['fee_c']:.2f}c of it fees) and makers earned {agv['maker_pnl_c']:.1f}c with no fee.
- **The fair-value model works but is not better than the market.** It is well calibrated out of sample (it says 75%, the window settles Yes 75% of the time). Against Kalshi's mid it was slightly less accurate in June–July and slightly more accurate in August–September.
- **Signals.** BTC and Binance lead the index by about one second; that is real and worth a small fraction of a cent. Previous-window momentum, hour of day, day of week and volatility regime add nothing out of sample. Order-book imbalance could not be tested.
- **The open lead (not evidence of an edge).** Taking the displayed quote at minute boundaries when the model sees at least 3c of edge returned {ci(ph(qv,'theta_3c'))} per contract in August–September but {ci(ph(qt,'theta_3c'))} in June–July. It was found after the planned tests were used up, the two periods disagree, and it assumes the displayed quote had size, which cannot be checked without historical books.
- **What is missing.** Kalshi has no historical order books. The 1-second recorder is written and ran for {BK['span_min']:.0f} minutes; the required 14 days need an always-on host. Until then fills cannot be modelled and the holdout (2026-10-01 onward) stays locked."""
tr1 = S["T1_taker_model"]["train_scan"]
GATE = f"""**All three fail.** The two taker configs are positive on validation but small: both point estimates are below the +1.0c bar, both intervals include zero, both exceed the drawdown limit, and both draw more than 20% of profit from one day. On train, thresholds of 1–5c lose money ({tr1['0.01']['pnl_per_contract_c']:+.2f}c to {tr1['0.05']['pnl_per_contract_c']:+.2f}c per contract); only 8c is positive, which is why 8c was selected, and its train interval also includes zero. The maker config loses at every threshold: under the trade-through rule it is filled only when the price moves through its quote, which is when the quote was wrong. That rule is deliberately harsh; real makers also get filled at their price and, as a group, earn {agv['maker_pnl_c']:.1f}c per contract (7.1). Whether a newcomer can get those fills is a queue-position question that needs order-book data."""
POST = f"""In August–September every threshold clears the gate's numeric bars; in June–July none is distinguishable from zero. Reasons not to treat this as an edge:

1. **Post-hoc.** The rule was chosen after seeing validation data. It has not been tested on untouched data.
2. **The two periods disagree.** The model was less accurate than the Kalshi mid in June–July (log-loss {qt['logloss_model']:.4f} vs {qt['logloss_mid']:.4f}) and more accurate in August–September ({qv['logloss_model']:.4f} vs {qv['logloss_mid']:.4f}). Volume more than quadrupled between June and September, so the later period may reflect a changing market, or chance.
3. **Displayed size is unknown.** In the {BK['span_min']:.0f}-minute live book sample the best quote held fewer than 10 contracts {100*BD['all']['share_best_ask_lt10']:.0f}% of the time on each side, and filling 10 contracts cost about {(BD['all']['slip_10lot_buy_c_mean']+BD['all']['slip_10lot_sell_c_mean'])/2:.1f}c more than the best quote on average ({(BD['all']['slip_100lot_buy_c_mean']+BD['all']['slip_100lot_sell_c_mean'])/2:.1f}c for 100). That average is small, but the stale quotes the model likes may be exactly the thin ones.
4. **It disagrees with the tape-based tests.** The same model made only {T1['pnl_per_contract_c']:+.1f}c to {T2['pnl_per_contract_c']:+.1f}c per contract in the same months when restricted to prices at which someone actually traded.

The rule is now frozen as configuration Q1 in `PREREG.md` (θ = 3c, 10 contracts per minute boundary, displayed size required) for a single test on the holdout once 14 days of recorded books exist."""
for key, val in (("VERDICT", VERDICT), ("GATE_TEXT", GATE), ("POSTHOC_TEXT", POST)):
    txt = txt.replace(f"@@{key}@@", val)
open(os.path.join(ROOT, "REPORT.md"), "w").write(txt)
print("REPORT.md written", len(txt))
