"""Tests of the research code on tiny made-up data. They prove the code is right (no leakage, correct formulas);
they say nothing about the real Kaggle dataset."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.payment_ml import data, experiment, history, metrics, models  # noqa: E402


def raw(rows):
    return pd.DataFrame([{
        "invoice_id": f"I{i}", "cust_number": r["c"], "posting_date": r["posted"],
        "due_in_date": int(r["due"].replace("-", "")), "clear_date": r.get("cleared"),
        "total_open_amount": r.get("amount", 100.0), "is_open": 0 if r.get("cleared") else 1,
        **({"cust_payment_terms": r["terms"]} if "terms" in r else {}),
    } for i, r in enumerate(rows)])


def prepared(rows):
    df, _ = data.prepare(raw(rows))
    return history.add_global_prior(history.add_customer_history(df))


# ---- labels ------------------------------------------------------------------------------

def test_delay_is_clear_date_minus_due_date():
    df = prepared([{"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-20"},
                   {"c": "A", "posted": "2020-01-02", "due": "2020-01-15", "cleared": "2020-01-12"}])
    assert list(df["delay"]) == [5.0, -3.0]


def test_an_open_invoice_has_no_delay_and_no_clear_date():
    df = prepared([{"c": "A", "posted": "2020-01-01", "due": "2020-01-15"}])
    assert np.isnan(df.loc[0, "delay"]) and pd.isna(df.loc[0, "clear"])


def test_an_invoice_cleared_before_it_was_posted_is_dropped_as_a_data_error():
    df, dropped = data.prepare(raw([{"c": "A", "posted": "2020-02-01", "due": "2020-02-15", "cleared": "2020-01-10"}]))
    assert len(df) == 0 and dropped["cleared_before_posting"] == 1


# ---- no future information -----------------------------------------------------------------

ROWS = [
    {"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-10"},   # delay -5
    {"c": "A", "posted": "2020-01-05", "due": "2020-01-20", "cleared": "2020-02-01"},   # delay +12
    {"c": "A", "posted": "2020-01-20", "due": "2020-02-10"},                            # open
    {"c": "A", "posted": "2020-01-10", "due": "2020-02-01"},                            # open, posted the day i0 cleared
]


def test_history_counts_only_payments_cleared_strictly_before_posting():
    df = prepared(ROWS)
    assert list(df["hist_n"]) == [0, 0, 1, 0]
    assert df.loc[2, "hist_p50"] == -5.0                 # only the first invoice was known on 2020-01-20


def test_open_invoices_never_count_as_history_or_as_a_zero_delay():
    df = prepared(ROWS)
    assert df["delay"].isna().sum() == 2
    assert df.loc[2, "hist_n"] == 1                       # the open invoices before it add nothing


def test_the_global_pool_uses_only_payments_cleared_before_the_posting_day():
    rows = ROWS + [{"c": "B", "posted": "2019-12-20", "due": "2020-01-01", "cleared": "2020-01-03"}]    # delay +2
    df = prepared(rows)
    assert np.isnan(df.loc[0, "glob_p50"])               # nothing was cleared before 2020-01-01
    assert df.loc[1, "glob_p50"] == 2.0                  # on 2020-01-05 only B's payment (01-03) was known


# ---- time split -----------------------------------------------------------------------------

def test_time_split_keeps_only_labels_that_were_observable_at_the_split():
    df = prepared([
        {"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-20"},   # train
        {"c": "A", "posted": "2020-02-10", "due": "2020-02-20", "cleared": "2020-03-15"},   # label unknown at the split
        {"c": "A", "posted": "2020-03-05", "due": "2020-03-25", "cleared": "2020-03-30"},   # test
        {"c": "A", "posted": "2020-03-06", "due": "2020-03-26"},                            # open: in neither
    ])
    train, test = experiment.time_split(df, pd.Timestamp("2020-03-01"), train_maturity_days=0)
    assert list(train.index) == [0] and list(test.index) == [2]
    assert (train["clear"] < pd.Timestamp("2020-03-01")).all() and (test["posting"] >= pd.Timestamp("2020-03-01")).all()


# ---- metrics ----------------------------------------------------------------------------------

def test_metric_examples_from_the_project_plan():
    assert metrics.mae([5, 10, 2], [7, 6, 2]) == 2.0
    assert metrics.pinball([10], [6], 0.75) == 3.0          # real above prediction: q * (y - p)
    assert metrics.pinball([2], [6], 0.75) == 1.0           # real below prediction: (1 - q) * (p - y)
    assert metrics.coverage([1, 5, 9], [2, 2, 2], [8, 8, 8]) == pytest.approx(1 / 3)
    assert metrics.rmse([0, 0], [3, 4]) == pytest.approx(np.sqrt(12.5))


# ---- baselines ----------------------------------------------------------------------------------

def test_on_time_baseline_predicts_zero_everywhere():
    p = models.predict_on_time(pd.DataFrame(index=range(3)))
    assert (p.to_numpy() == 0).all() and list(p.columns) == ["p25", "p50", "p75"]


def test_customer_median_uses_own_numbers_from_five_invoices_else_the_shared_ones_else_zero():
    df = pd.DataFrame({
        "hist_n": [5, 4, 0], "hist_p25": [1.0, 1.0, np.nan], "hist_p50": [5.0, 5.0, np.nan], "hist_p75": [12.0, 12.0, np.nan],
        "glob_p25": [0.0, 2.0, np.nan], "glob_p50": [3.0, 4.0, np.nan], "glob_p75": [9.0, 8.0, np.nan]})
    p = models.predict_customer_median(df)
    assert p.loc[0].tolist() == [1, 5, 12]                  # five paid invoices: own
    assert p.loc[1].tolist() == [2, 4, 8]                   # four: shared
    assert p.loc[2].tolist() == [0, 0, 0]                   # no history at all: on time


# ---- audit and loading ------------------------------------------------------------------------

def test_audit_reports_what_the_file_contains_without_assuming_anything():
    frame = raw([{"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-20"},
                 {"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-20"},
                 {"c": "B", "posted": "2020-02-01", "due": "2020-02-15"},
                 {"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-20", "amount": 999.0}])
    frame.loc[1, "invoice_id"] = frame.loc[0, "invoice_id"]          # row 1 is an exact copy of row 0
    frame.loc[3, "invoice_id"] = frame.loc[0, "invoice_id"]          # row 3 reuses the id but is a different row
    frame["invoice_currency"] = ["USD", "USD", "CAD", "USD"]
    frame["area_business"] = np.nan
    a = data.audit(frame)
    assert a["rows"] == 4 and a["exact_duplicate_rows"] == 1
    assert a["rows_with_repeated_invoice_id"] == 3 and a["repeated_invoice_id_but_not_identical_rows"] == 1
    assert a["labelled_rows"] == 3 and a["open_rows"] == 1 and a["empty_columns"] == ["area_business"]
    assert a["currencies"] == {"USD": 3, "CAD": 1} and a["customers"] == 2


def test_load_csv_explains_a_missing_column(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("cust_number,posting_date\nA,2020-01-01\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no column"):
        data.load_csv(path)


def test_load_csv_accepts_the_original_column_names(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("clear_date,due_in_date,cust_number,total_open_amount,posting_date,isOpen\n"
                    "2020-01-20,20200115,A,10.5,2020-01-01,0\n", encoding="utf-8")
    assert data.load_csv(path).loc[0, "is_open"] == 0


# ---- the model and the decision rule ---------------------------------------------------------

def _synthetic(customers=6, per_customer=120, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(customers):
        for day in pd.date_range("2020-01-01", periods=per_customer):
            due = day + pd.Timedelta(days=30)
            delay = c * 3 + int(rng.integers(-1, 2))
            rows.append({"c": f"C{c}", "posted": str(day.date()), "due": str(due.date()),
                         "cleared": str((due + pd.Timedelta(days=delay)).date()), "terms": "N30" if c % 2 else "N45"})
    return rows


def test_lightgbm_runs_keeps_quantiles_ordered_and_handles_an_unseen_category():
    df = prepared(_synthetic(per_customer=240))
    df = models.add_basic_features(df)
    train, test = experiment.time_split(df, pd.Timestamp("2020-06-01"))
    numeric, categorical = models.feature_columns(df)
    assert categorical == ["cust_payment_terms"]
    model = models.LightGBMQuantiles(n_estimators=60).fit(train, numeric, categorical)
    test = test.copy()
    test.loc[test.index[0], "cust_payment_terms"] = "NEVER_SEEN"
    p = models.predict_delay_quantiles(model, test)
    assert len(p) == len(test) and not p.isna().any().any()
    assert (p["p25"] <= p["p50"]).all() and (p["p50"] <= p["p75"]).all()
    assert metrics.mae(test["delay"], p["p50"]) < metrics.mae(test["delay"], models.predict_on_time(test)["p50"])


def test_run_is_reproducible(tmp_path):
    path = tmp_path / "synthetic.csv"
    frame = raw(_synthetic(customers=4, per_customer=220))
    frame.rename(columns={"is_open": "isOpen"}).to_csv(path, index=False)
    a = experiment.run(path, "2020-05-15")
    b = experiment.run(path, "2020-05-15")
    assert a["overall"] == b["overall"] and a["train_rows"] > 0 and a["test_rows"] > 0
    assert "Use ML" in experiment.report_markdown(a)


def test_training_keeps_only_invoices_old_enough_to_have_been_cleared_if_they_were_going_to_be():
    df = prepared([
        {"c": "A", "posted": "2020-01-01", "due": "2020-01-15", "cleared": "2020-01-20"},   # due 46 days before the split
        {"c": "A", "posted": "2020-01-20", "due": "2020-02-20", "cleared": "2020-02-10"},   # due 10 days before: paid early, would bias
        {"c": "A", "posted": "2019-11-01", "due": "2019-12-01", "cleared": "2019-12-05"},   # due 91 days before the split
    ])
    split = pd.Timestamp("2020-03-01")
    train, _ = experiment.time_split(df, split, train_maturity_days=60)
    assert list(train.index) == [2]
    assert list(experiment.time_split(df, split, train_maturity_days=30)[0].index) == [0, 2]


def test_test_end_drops_later_invoices_from_the_test_set():
    df = prepared([
        {"c": "A", "posted": "2020-03-05", "due": "2020-03-25", "cleared": "2020-03-30"},
        {"c": "A", "posted": "2020-04-05", "due": "2020-04-25", "cleared": "2020-04-30"},
    ])
    _, everything = experiment.time_split(df, pd.Timestamp("2020-03-01"))
    _, window = experiment.time_split(df, pd.Timestamp("2020-03-01"), pd.Timestamp("2020-04-01"))
    assert len(everything) == 2 and list(window.index) == [0]


def test_open_invoices_are_counted_inside_and_after_the_test_window(tmp_path):
    rows = _synthetic(customers=3, per_customer=220)
    rows.append({"c": "C0", "posted": "2020-05-20", "due": "2020-06-20"})      # open, inside the window
    rows.append({"c": "C0", "posted": "2020-09-01", "due": "2020-10-01"})      # open, after the last labelled invoice
    path = tmp_path / "s.csv"
    raw(rows).rename(columns={"is_open": "isOpen"}).to_csv(path, index=False)
    r = experiment.run(path, "2020-05-15")
    assert r["open_invoices_inside_test_window"] == 1 and r["open_invoices_after_test_window"] == 1


def test_rolling_splits_never_pass_the_cap_and_ml_must_win_everywhere(tmp_path):
    df = prepared(_synthetic())
    splits = experiment.rolling_splits(df, first="2020-02-01", last="2020-03-01", months=2, cap="2020-04-01")
    assert [(str(a.date()), str(b.date())) for a, b in splits] == [("2020-02-01", "2020-04-01"), ("2020-03-01", "2020-04-01")]
    base = {"mae": 10.0, "pinball_p25": 1.0, "pinball_p50": 2.0, "pinball_p75": 3.0, "coverage_p25_p75": 0.5}
    good = {"mae": 8.0, "pinball_p25": 0.9, "pinball_p50": 1.9, "pinball_p75": 2.9, "coverage_p25_p75": 0.5}
    bad = {**good, "mae": 12.0}
    def block(ml):
        return {"split": "x", "test_end": "y", "train_rows": 1, "test_rows": 1,
                "overall": {"all customers pay on time": base, "customer median": base, "LightGBM": ml},
                "verdict": experiment.verdict(base, ml)}
    mixed = {"splits": [block(good), block(bad)], "ml_wins": 1, "of": 2, "use_ml_everywhere": False}
    assert "keep the customer median" in experiment.rolling_markdown(mixed)


def test_the_command_line_runs_and_writes_the_reports(tmp_path, monkeypatch, capsys):
    csv = tmp_path / "synthetic.csv"
    raw(_synthetic(customers=4, per_customer=220)).rename(columns={"is_open": "isOpen"}).to_csv(csv, index=False)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["experiment", "--csv", str(csv), "--split-date", "2020-05-15", "--out", str(out)])
    experiment.main()
    assert {p.name for p in out.iterdir()} == {"audit.json", "metrics.json", "report.md"}
    assert "Decision" in capsys.readouterr().out


def test_help_text_is_valid(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["experiment", "--help"])
    with pytest.raises(SystemExit) as stop:
        experiment.main()
    assert stop.value.code == 0 and "--split-date" in capsys.readouterr().out


def test_ml_is_adopted_only_when_it_beats_the_baseline_by_ten_percent_and_on_pinball():
    base = {"mae": 10.0, "pinball_p25": 1.0, "pinball_p50": 2.0, "pinball_p75": 3.0, "coverage_p25_p75": 0.5}
    good = {"mae": 8.9, "pinball_p25": 0.9, "pinball_p50": 1.9, "pinball_p75": 2.9, "coverage_p25_p75": 0.5}
    assert experiment.verdict(base, good)["use_ml"]
    assert not experiment.verdict(base, {**good, "mae": 9.2})["use_ml"]                    # only 8% better
    assert not experiment.verdict(base, {**good, "pinball_p75": 3.1})["use_ml"]            # worse at one quantile
    assert experiment.verdict(base, {**good, "coverage_p25_p75": 0.9})["use_ml"]           # coverage is reported, not a gate
