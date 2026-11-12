"""Features from what is already known about a customer when an invoice is posted. No future information.

An earlier payment counts for invoice i only if it was CLEARED STRICTLY BEFORE invoice i's posting date, and only
paid invoices count (open ones are never treated as a delay of 0)."""
import numpy as np
import pandas as pd

MIN_HISTORY = 5
QUANTILES = (0.25, 0.5, 0.75)
NAMES = ("p25", "p50", "p75")


def add_customer_history(df: pd.DataFrame) -> pd.DataFrame:
    out = df.reset_index(drop=True).copy()
    n = len(out)
    hist_n = np.zeros(n, dtype=int)
    hist_mean = np.full(n, np.nan)
    late_share = np.full(n, np.nan)
    hist_q = {name: np.full(n, np.nan) for name in NAMES}

    paid = out[out["delay"].notna()].sort_values("clear")
    paid_by_customer = {c: (g["clear"].to_numpy(), g["delay"].to_numpy()) for c, g in paid.groupby("customer")}
    for customer, rows in out.groupby("customer"):
        if customer not in paid_by_customer:
            continue
        clear_sorted, delay_sorted = paid_by_customer[customer]
        late_cum = np.cumsum(delay_sorted > 0)
        sum_cum = np.cumsum(delay_sorted)
        counts = np.searchsorted(clear_sorted, rows["posting"].to_numpy(), side="left")   # cleared strictly before
        for i, k in zip(rows.index, counts):
            if k == 0:
                continue
            hist_n[i] = k
            hist_mean[i] = sum_cum[k - 1] / k
            late_share[i] = late_cum[k - 1] / k
            for name, value in zip(NAMES, np.quantile(delay_sorted[:k], QUANTILES)):
                hist_q[name][i] = value

    out["hist_n"] = hist_n
    out["hist_mean"] = hist_mean
    out["hist_late_share"] = late_share
    for name in NAMES:
        out[f"hist_{name}"] = hist_q[name]
    return out


def add_global_prior(df: pd.DataFrame) -> pd.DataFrame:
    """P25/P50/P75 of every customer's delays cleared strictly before each posting day (the fallback pool)."""
    out = df.copy()
    paid = out[out["delay"].notna()].sort_values("clear")
    clear_sorted, delay_sorted = paid["clear"].to_numpy(), paid["delay"].to_numpy()
    day = out["posting"].dt.normalize()
    table = {}
    for d in day.unique():
        k = np.searchsorted(clear_sorted, np.datetime64(d), side="left")
        table[pd.Timestamp(d)] = np.quantile(delay_sorted[:k], QUANTILES) if k else (np.nan, np.nan, np.nan)
    for j, name in enumerate(NAMES):
        out[f"glob_{name}"] = day.map(lambda t, j=j: table[pd.Timestamp(t)][j]).astype(float)
    return out
