"""Compare three predictors of the payment delay on a time-based split, using only information known at the time.

    python -m research.payment_ml.experiment --csv research/data/payment_date.csv [--split-date 2020-01-01]

Split: invoices posted before the split date AND already cleared before it are used for training (their labels
were observable then); invoices posted on or after it are the test set. Open invoices have no label and are
excluded everywhere, which makes the test set look easier than reality (late payers are still open): the report
counts them so the bias is visible. Nothing here is a statement about real companies: see the caveats."""
import argparse
import json
from pathlib import Path

import pandas as pd

from . import data, history, metrics, models

CRITERIA = "criteria are the project's proposed targets, not a standard"


MATURITY_DAYS = 60     # the audit shows P99 of the delay is about 50 days: after 60 days nearly every invoice is cleared


def time_split(df: pd.DataFrame, split: pd.Timestamp, test_end: pd.Timestamp | None = None,
               train_maturity_days: int = MATURITY_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train: posted before `split`, cleared before it (the label was observable), and DUE at least `train_maturity_days`
    before it. The last condition matters: an invoice due just before the split is in the data only if it was paid early,
    because the late payers are not cleared yet. Keeping those would teach the model that invoices due close to the split
    are paid early (it was measured: a bias of about -4.7 days on the test set).
    Test: posted from `split` up to (not including) `test_end`."""
    labelled = df[df["delay"].notna()]
    train = labelled[(labelled["posting"] < split) & (labelled["clear"] < split)
                     & (labelled["due"] <= split - pd.Timedelta(days=train_maturity_days))]
    test = labelled[labelled["posting"] >= split]
    if test_end is not None:
        test = test[test["posting"] < test_end]
    return train, test


def default_split(df: pd.DataFrame) -> pd.Timestamp:
    return df[df["delay"].notna()]["posting"].quantile(0.8).normalize()


def verdict(baseline: dict, ml: dict) -> dict:
    improvement = 1 - ml["mae"] / baseline["mae"] if baseline["mae"] else 0.0
    checks = {
        "MAE at least 10% lower than the customer-median baseline": improvement >= 0.10,
        "pinball loss lower than the baseline at P25, P50 and P75":
            all(ml[k] < baseline[k] for k in ("pinball_p25", "pinball_p50", "pinball_p75")),
        "coverage of P25-P75 between 40% and 60%": 0.40 <= ml["coverage_p25_p75"] <= 0.60,
    }
    first_two = list(checks.values())[:2]
    return {"mae_improvement": improvement, "checks": checks, "use_ml": all(first_two), "note": CRITERIA}


def build_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Cleaned invoices with the delay, the leak-free customer history and the basic features."""
    df, dropped = data.prepare(raw)
    return models.add_basic_features(history.add_global_prior(history.add_customer_history(df))), dropped


def rolling_splits(df: pd.DataFrame, first="2019-06-01", last="2019-12-01", months=2, cap="2020-02-01"):
    """Monthly split dates with a test window of `months` months, never past `cap` (the first month that is partly open)."""
    cap = pd.Timestamp(cap)
    out = []
    for split in pd.date_range(first, last, freq="MS"):
        out.append((split, min(split + pd.DateOffset(months=months), cap)))
    return out


def rolling(csv_path, **kw) -> dict:
    """The same comparison at several split dates. ML is only trusted when it wins on every one of them."""
    raw = data.load_csv(csv_path)
    df, _ = build_frame(raw)
    numeric, categorical = models.feature_columns(df)
    rows = []
    for split, end in rolling_splits(df, **kw):
        train, test = time_split(df, split, end)
        if len(train) < 1000 or len(test) < 200:
            continue
        ml = models.LightGBMQuantiles().fit(train, numeric, categorical)
        overall = {"all customers pay on time": metrics.evaluate(test["delay"], models.predict_on_time(test)),
                   "customer median": metrics.evaluate(test["delay"], models.predict_customer_median(test)),
                   "LightGBM": metrics.evaluate(test["delay"], ml.predict(test))}
        rows.append({"split": str(split.date()), "test_end": str(end.date()), "train_rows": int(len(train)),
                     "test_rows": int(len(test)), "overall": overall, "verdict": verdict(overall["customer median"], overall["LightGBM"])})
    wins = sum(r["verdict"]["use_ml"] for r in rows)
    return {"splits": rows, "ml_wins": wins, "of": len(rows), "use_ml_everywhere": bool(rows) and wins == len(rows)}


def rolling_markdown(result: dict) -> str:
    out = ["# Rolling-origin check: does ML win at every split date?", "",
           "| Split | Test window end | Train | Test | MAE on time | MAE customer median | MAE LightGBM | Gain | ML passes |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in result["splits"]:
        o = r["overall"]
        out.append(f"| {r['split']} | {r['test_end']} | {r['train_rows']} | {r['test_rows']} | {o['all customers pay on time']['mae']:.2f} | "
                   f"{o['customer median']['mae']:.2f} | {o['LightGBM']['mae']:.2f} | {r['verdict']['mae_improvement']:+.1%} | "
                   f"{'yes' if r['verdict']['use_ml'] else 'no'} |")
    out += ["", f"ML passes the two main criteria at {result['ml_wins']} of {result['of']} split dates. "
                f"**Use ML: {'yes' if result['use_ml_everywhere'] else 'no, keep the customer median'}** "
                "(the rule is: ML must win at every split date).", ""]
    return "\n".join(out)


def run(csv_path, split_date=None, test_end=None) -> dict:
    raw = data.load_csv(csv_path)
    audit = data.audit(raw)
    df, dropped = build_frame(raw)
    split = pd.Timestamp(split_date) if split_date else default_split(df)
    last_labelled = df[df["delay"].notna()]["posting"].max() + pd.Timedelta(days=1)
    end = pd.Timestamp(test_end) if test_end else last_labelled
    train, test = time_split(df, split, end)
    if train.empty or test.empty:
        raise ValueError(f"split {split.date()} leaves {len(train)} training and {len(test)} test invoices")

    numeric, categorical = models.feature_columns(df)
    ml = models.LightGBMQuantiles().fit(train, numeric, categorical)
    predictions = {
        "all customers pay on time": models.predict_on_time(test),
        "customer median": models.predict_customer_median(test),
        "LightGBM": ml.predict(test),
    }
    y = test["delay"]
    overall = {name: metrics.evaluate(y, p) for name, p in predictions.items()}
    enough = test["hist_n"] >= history.MIN_HISTORY
    segments = {}
    for label, mask in (("customer has 5+ earlier paid invoices", enough), ("fewer than 5 (shared numbers)", ~enough)):
        if mask.any():
            segments[label] = {name: metrics.evaluate(y[mask], p[mask]) for name, p in predictions.items()}
    return {
        "split_date": str(split.date()), "test_end": str(end.date()), "train_rows": int(len(train)), "test_rows": int(len(test)),
        # still open inside the test window: late payers missing from the test set (a real bias)
        "open_invoices_inside_test_window": int(((df["delay"].isna()) & (df["posting"] >= split) & (df["posting"] < end)).sum()),
        # still open and posted after the test window: simply no label yet, outside any evaluation
        "open_invoices_after_test_window": int(((df["delay"].isna()) & (df["posting"] >= end)).sum()),
        "features": {"numeric": numeric, "categorical": categorical},
        "dropped_while_preparing": dropped, "audit": audit,
        "overall": overall, "by_history": segments,
        "verdict": verdict(overall["customer median"], overall["LightGBM"]),
        "caveats": [
            "Open invoices have no delay and are excluded; if some are posted inside the test window, late payers are under-represented in it.",
            "Amounts are not converted between currencies.",
            "The data is not from a Vietnamese company: do not transfer the model to Minh Phat or any other company by default.",
            "Check the dataset license on its Kaggle page before using or sharing it.",
        ],
    }


def report_markdown(result: dict) -> str:
    def table(block: dict) -> list[str]:
        lines = ["| Predictor | n | MAE (days) | RMSE | Pinball P25 | Pinball P50 | Pinball P75 | Coverage P25-P75 |", "|---|---|---|---|---|---|---|---|"]
        for name, m in block.items():
            lines.append(f"| {name} | {m['n']} | {m['mae']:.2f} | {m['rmse']:.2f} | {m['pinball_p25']:.2f} | "
                         f"{m['pinball_p50']:.2f} | {m['pinball_p75']:.2f} | {m['coverage_p25_p75']:.0%} |")
        return lines

    v = result["verdict"]
    out = ["# Payment delay: baselines against LightGBM", "",
           f"Split date {result['split_date']}, test window up to {result['test_end']} (exclusive): {result['train_rows']} training "
           f"and {result['test_rows']} test invoices.",
           f"Open invoices posted inside the test window (no label, so missing from the test set): {result['open_invoices_inside_test_window']}. "
           f"Open invoices posted after the window (no label yet, outside any evaluation): {result['open_invoices_after_test_window']}.", "",
           "## All test invoices", ""] + table(result["overall"])
    for label, block in result["by_history"].items():
        out += ["", f"## {label}", ""] + table(block)
    out += ["", "## Decision", "", f"MAE improvement over the customer median: {v['mae_improvement']:.1%}", ""]
    out += [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in v["checks"].items()]
    out += ["", f"**Use ML: {'yes' if v['use_ml'] else 'no, keep the customer median'}** ({v['note']}).", "", "## Caveats", ""]
    out += [f"- {c}" for c in result["caveats"]]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", required=True, help="path to the Kaggle payment-date CSV (keep it out of git)")
    parser.add_argument("--split-date", help="YYYY-MM-DD; default is the date after 80%% of the labelled invoices")
    parser.add_argument("--test-end", help="YYYY-MM-DD (exclusive): ignore test invoices posted from this date, e.g. to drop a month that is still partly open")
    parser.add_argument("--rolling", action="store_true", help="evaluate monthly split dates 2019-06 .. 2019-12 instead of one")
    parser.add_argument("--out", default="research/results", help="folder for audit.json, metrics.json and report.md")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.rolling:
        result = rolling(args.csv)
        (out / "rolling.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        (out / "rolling.md").write_text(rolling_markdown(result), encoding="utf-8")
        print(rolling_markdown(result))
        return
    result = run(args.csv, args.split_date, args.test_end)
    (out / "audit.json").write_text(json.dumps(result["audit"], indent=2, default=str), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(report_markdown(result), encoding="utf-8")
    print(report_markdown(result))
    print(f"written to {out}/")


if __name__ == "__main__":
    main()
