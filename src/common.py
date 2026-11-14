"""Shared constants and loaders. Holdout guard lives here."""
import os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TRAIN = ("2026-02-11", "2026-07-31")
VALID = ("2026-08-01", "2026-09-30")
HOLDOUT_START = "2026-10-01"
MICRO_START = "2026-06-01"  # first day with trades/quotes downloaded


def split_of(date_str):
    if date_str >= HOLDOUT_START:
        return "holdout"
    if date_str >= VALID[0]:
        return "valid"
    return "train"


def load_markets():
    m = pd.read_csv(os.path.join(DATA, "markets.csv"))
    m["close_ts"] = pd.to_datetime(m["close_time"], utc=True)
    m["open_ts"] = pd.to_datetime(m["open_time"], utc=True)
    m["date"] = m["close_ts"].dt.strftime("%Y-%m-%d")
    m["split"] = m["date"].map(split_of)
    if os.environ.get("UNLOCK_HOLDOUT") != "1":
        m = m[m["split"] != "holdout"].copy()
    return m.sort_values("close_ts").reset_index(drop=True)
