"""Loading, auditing and cleaning the payment-date CSV.

Nothing here assumes a row count, a license or any statistic: the audit reports what the file really contains.
A delay is (clear date - due date) in days: negative = paid early. An invoice that is still open has NO delay
(NaN). It is never given a delay of 0."""
import re

import numpy as np
import pandas as pd

REQUIRED = ["clear_date", "due_in_date", "cust_number", "total_open_amount", "posting_date", "is_open"]


def _normalise(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip()).strip("_").lower()
    return {"isopen": "is_open"}.get(name, name)


def load_csv(path) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    raw.columns = [_normalise(c) for c in raw.columns]
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError(f"the file has no column(s) {missing}; columns found: {list(raw.columns)}")
    return raw


def _dates(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=raw.index)
    due = pd.to_numeric(raw["due_in_date"], errors="coerce").astype("Int64").astype("string")   # 20200210
    df["due"] = pd.to_datetime(due, format="%Y%m%d", errors="coerce")
    df["posting"] = pd.to_datetime(raw["posting_date"], errors="coerce")
    df["clear"] = pd.to_datetime(raw["clear_date"], errors="coerce")
    return df


def audit(raw: pd.DataFrame) -> dict:
    """What the file contains. Reports only; it asserts nothing about the numbers quoted in the project plan."""
    d = _dates(raw)
    is_open = pd.to_numeric(raw["is_open"], errors="coerce")
    labelled = (is_open == 0) & d["clear"].notna()
    delay = (d["clear"] - d["due"]).dt.days.where(labelled)
    cust = raw["cust_number"].astype(str)
    paid_per_customer = cust[labelled].value_counts()
    info = {
        "rows": int(len(raw)),
        "columns": list(raw.columns),
        "empty_columns": [c for c in raw.columns if raw[c].isna().all()],
        "null_share": {c: round(float(raw[c].isna().mean()), 4) for c in raw.columns if raw[c].isna().any()},
        "exact_duplicate_rows": int(raw.duplicated().sum()),
        "rows_with_repeated_invoice_id": int(raw["invoice_id"].duplicated(keep=False).sum()) if "invoice_id" in raw else None,
        "repeated_invoice_id_but_not_identical_rows": (
            int(raw["invoice_id"].duplicated(keep=False).sum() - raw[raw["invoice_id"].duplicated(keep=False)].duplicated(keep=False).sum())
            if "invoice_id" in raw else None),
        "currencies": raw["invoice_currency"].value_counts(dropna=False).to_dict() if "invoice_currency" in raw else None,
        "is_open_values": is_open.value_counts(dropna=False).to_dict(),
        "labelled_rows": int(labelled.sum()),
        "open_rows": int((is_open == 1).sum()),
        "closed_without_clear_date": int(((is_open == 0) & d["clear"].isna()).sum()),
        "open_but_has_clear_date": int(((is_open == 1) & d["clear"].notna()).sum()),
        "unparsable_due_or_posting_date": int((d["due"].isna() | d["posting"].isna()).sum()),
        "cleared_before_posting": int((labelled & (d["clear"] < d["posting"])).sum()),
        "posting_date_range": [str(d["posting"].min().date()), str(d["posting"].max().date())] if d["posting"].notna().any() else None,
        "due_date_range": [str(d["due"].min().date()), str(d["due"].max().date())] if d["due"].notna().any() else None,
        "clear_date_range": [str(d["clear"].min().date()), str(d["clear"].max().date())] if d["clear"].notna().any() else None,
        "customers": int(cust.nunique()),
        "customers_with_5_or_more_paid_invoices": int((paid_per_customer >= 5).sum()),
        "delay_days_percentiles": ({str(q): float(np.quantile(delay.dropna(), q)) for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)}
                                   if delay.notna().any() else None),
    }
    return info


def prepare(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One row per invoice with parsed dates, the delay (NaN while open) and a list of what was dropped and why."""
    dropped = {}
    before = len(raw)
    raw = raw.drop_duplicates()
    dropped["exact_duplicate_rows"] = before - len(raw)

    df = _dates(raw)
    df["customer"] = raw["cust_number"].astype(str)
    df["amount"] = pd.to_numeric(raw["total_open_amount"], errors="coerce")
    is_open = pd.to_numeric(raw["is_open"], errors="coerce")
    for extra in ("invoice_id", "cust_payment_terms", "business_code", "invoice_currency", "document_type"):
        if extra in raw.columns:
            df[extra] = raw[extra]

    labelled = (is_open == 0) & df["clear"].notna()
    df["delay"] = (df["clear"] - df["due"]).dt.days.where(labelled).astype(float)
    df.loc[~labelled, "clear"] = pd.NaT          # an open invoice has no clear date to be used anywhere

    keep = df["due"].notna() & df["posting"].notna()
    dropped["unparsable_due_or_posting_date"] = int((~keep).sum())
    df = df[keep]
    anomaly = df["delay"].notna() & (df["clear"] < df["posting"])   # paid before it was posted: a data error
    dropped["cleared_before_posting"] = int(anomaly.sum())
    df = df[~anomaly].reset_index(drop=True)
    return df, dropped
