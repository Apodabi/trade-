# Pre-registration — KXXRP15M edge study

Written and committed **before** any outcome, trade or quote data was analysed.
Disclosure: while probing API shapes I saw the result of four individual
windows (three on 2026-11-14, one each on 2026-03-01 / 06-01 / 09-01 as
single-market probes). No statistics were computed from them.

## Date split (by market `close_time`, UTC date)

| Split | Dates | Use |
|---|---|---|
| Train | 2026-02-11 → 2026-07-31 | fit volatility model, choose signals and thresholds |
| Validation | 2026-08-01 → 2026-09-30 | one-shot evaluation of frozen configs |
| Holdout | 2026-10-01 → onward | **locked**. Not read by any analysis code in this study |

`src/common.py::load_markets` drops holdout rows unless an explicit
`UNLOCK_HOLDOUT=1` is set, and no trades/quotes/index are downloaded for the
holdout period in this study.

Market-microstructure data (trades, 1-min quotes) is pulled for
2026-06-01 → 2026-09-30 only (API-call budget); "train" for anything that
needs market prices therefore means 2026-06-01 → 2026-07-31. Index and
settled outcomes are used for the whole train range.

## Model/selection discipline

- All parameters (vol estimator, any signal coefficient, entry threshold,
  time/distance filters) are chosen on train only.
- At most **3** frozen strategy configurations are evaluated on validation.
- Signals are tested one at a time against the baseline; a signal is kept
  only if it lowers train log-loss and the improvement has the same sign on
  validation.

## Execution assumptions (fixed)

- Decision latency 1 second: a signal computed from data through second `t`
  can trade no earlier than second `t+1`.
- Taker fills only against liquidity that demonstrably existed: without
  historical books, a taker buy at price `p` is counted as fillable only if
  the public tape shows a taker trade on the same side at a price `<= p`
  (for buys) in the execution second, and only up to that printed size.
- Maker orders are filled only if a later trade prints strictly through the
  resting price (trade-through); a print at the price is not a fill.
- Fees charged per Kalshi's published formula for the series' `fee_type`,
  rounded up per order.
- No trading in the final 10 seconds, when the index series has a gap, when
  there is no two-sided market, or during the weekly maintenance pause.

## Pass gate (all must hold on validation, frozen config)

1. **Sample size:** >= 500 traded windows on >= 40 distinct days.
2. **Expectancy:** mean net P&L >= +1.0 cent per contract after fees, and the
   day-block bootstrap 95% CI lower bound > 0.
3. **Drawdown:** with a flat cap of 100 contracts per window, max
   peak-to-trough drawdown <= $1,000 (10 max-stakes).
4. **Concentration:** no single UTC day contributes more than 20% of total
   net profit.
5. **Realism:** 1-4 computed under the execution assumptions above.

Verdict mapping:
- all five pass -> "candidate edge" (holdout may then be unlocked once, but
  only after >= 14 days of 1-second order-book recordings exist to model fills);
- gate evaluated and failed -> "no edge";
- data cannot support the test (too few windows, or fills cannot be modelled
  credibly) -> "not enough data".
