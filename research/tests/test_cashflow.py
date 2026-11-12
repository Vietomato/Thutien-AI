"""Tests for the weekly cash-flow backtest: the delay distributions, the week arithmetic, the simulation and the truth."""
import numpy as np
import pandas as pd
import pytest

from research.payment_ml import cashflow as cf

T = pd.Timestamp("2019-06-03")


def invoices(rows):
    """rows: (customer, due, posting, clear or None, amount)"""
    df = pd.DataFrame(rows, columns=["customer", "due", "posting", "clear", "amount"])
    for c in ("due", "posting", "clear"):
        df[c] = pd.to_datetime(df[c])
    df["delay"] = (df["clear"] - df["due"]).dt.days.astype(float)
    return df


def known_with(customer_delays: dict[str, list[int]]):
    rows = []
    for customer, delays in customer_delays.items():
        for i, d in enumerate(delays):
            due = T - pd.Timedelta(days=90 + 3 * i)
            rows.append((customer, due, due - pd.Timedelta(days=30), due + pd.Timedelta(days=d), 100.0))
    return invoices(rows)


def open_with(rows):
    return invoices([(c, due, T - pd.Timedelta(days=40), None, amt) for c, due, amt in rows])


def test_truth_is_what_the_open_invoices_really_paid_per_week():
    df = invoices([
        ("a", "2019-05-20", "2019-04-20", "2019-06-03", 100.0),   # open at T, pays on day 0 -> week 0
        ("b", "2019-05-20", "2019-04-20", "2019-06-12", 50.0),    # day 9 -> week 1
        ("c", "2019-05-20", "2019-04-20", "2019-09-30", 70.0),    # beyond the 12 weeks: not counted
        ("d", "2019-05-01", "2019-04-01", "2019-05-15", 999.0),   # already cleared before T: not open
    ])
    o = cf.make_origin(df, T)
    assert len(o.open) == 3 and len(o.known) == 1
    assert o.actual[0] == 100.0 and o.actual[1] == 50.0 and o.actual.sum() == 150.0


def test_an_open_invoice_that_never_clears_in_the_file_is_refused():
    df = invoices([("a", "2019-05-20", "2019-04-20", None, 100.0)])
    with pytest.raises(ValueError):
        cf.make_origin(df, T)


def test_every_distribution_is_a_probability_distribution():
    known = known_with({"a": [0, 2, 4, 6, 8, 10], "b": [30, 31]})
    open_ = open_with([("a", T - pd.Timedelta(days=5), 10.0), ("b", T + pd.Timedelta(days=9), 20.0), ("new", T, 30.0)])
    glob, per = cf.pools(known, T, None)
    weights, offset, fallback = cf.distributions(open_, T, glob, per, k=5)
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert not fallback.any()


def test_not_paid_yet_removes_delays_shorter_than_the_days_already_overdue():
    known = known_with({"a": [0, 1, 2, 3, 20, 25, 30, 40]})
    open_ = open_with([("a", T - pd.Timedelta(days=10), 10.0)])      # 10 days overdue
    glob, per = cf.pools(known, T, None)
    weights, offset, _ = cf.distributions(open_, T, glob, per, k=5)
    assert weights[0][cf.BINS < 10].sum() == 0.0
    assert offset[0][weights[0] > 0].min() >= 0                       # nothing is predicted for the past


def test_history_beyond_everything_seen_falls_back_to_counting_from_today():
    known = known_with({"a": [0, 1, 2, 3, 4, 5]})
    open_ = open_with([("a", T - pd.Timedelta(days=300), 10.0)])     # later than any delay on record
    glob, per = cf.pools(known, T, None)
    weights, offset, fallback = cf.distributions(open_, T, glob, per, k=5)
    assert fallback[0] and np.isclose(weights[0].sum(), 1.0)
    assert offset[0][weights[0] > 0].min() >= 1


def test_shrinkage_trusts_a_long_history_and_discounts_a_short_one():
    known = known_with({"long": [20] * 40, "short": [20], "others": [0] * 60})
    open_ = open_with([("long", T + pd.Timedelta(days=30), 1.0), ("short", T + pd.Timedelta(days=30), 1.0)])
    glob, per = cf.pools(known, T, None)
    weights, _, _ = cf.distributions(open_, T, glob, per, k=5)
    at_20 = weights[:, 20 - cf.BMIN]
    assert at_20[0] > 0.8 > at_20[1]                                  # 40 invoices vs 1 invoice of the same behaviour


def test_recent_payments_weigh_more_when_a_half_life_is_set():
    old = known_with({"a": [0, 0, 0]})
    recent = old.copy()
    recent["delay"], recent["clear"] = 30.0, T - pd.Timedelta(days=5)
    known = pd.concat([old, recent], ignore_index=True)
    plain, _ = cf.pools(known, T, None)
    decayed, _ = cf.pools(known, T, 30)
    assert decayed[30 - cf.BMIN] / decayed.sum() > plain[30 - cf.BMIN] / plain.sum()


def test_week_probabilities_follow_the_payment_date():
    weights = np.zeros((1, cf.NB))
    weights[0, 10 - cf.BMIN] = 1.0                                    # certain delay of 10 days
    offset = (np.array([5]) + cf.BINS[None, :])                       # due in 5 days -> pays on day 15 -> week 2
    p = cf.week_probabilities(weights, offset)
    assert p[0, 2] == 1.0 and p.sum() == 1.0


def test_probability_beyond_the_last_week_is_not_counted():
    weights = np.zeros((1, cf.NB))
    weights[0, 200 - cf.BMIN] = 1.0
    p = cf.week_probabilities(weights, np.array([0]) + cf.BINS[None, :])
    assert p.sum() == 0.0


def test_simulation_of_a_certain_payment_reproduces_it_exactly():
    weights = np.zeros((2, cf.NB))
    weights[:, 3 - cf.BMIN] = 1.0
    offset = np.array([[0], [7]]) + cf.BINS[None, :]                  # pays on day 3 and day 10 -> weeks 0 and 1
    runs = cf.simulate(weights, offset, np.array([100.0, 40.0]), np.array(["a", "b"]), share=0.5, shock_days=0, sims=20, rng=np.random.default_rng(1))
    assert (runs[:, 0] == 100.0).all() and (runs[:, 1] == 40.0).all() and runs[:, 2:].sum() == 0.0


def test_a_common_shock_moves_the_whole_period_and_never_into_the_past():
    weights = np.zeros((1, cf.NB))
    weights[0, 0 - cf.BMIN] = 1.0
    offset = np.array([[0]]) + cf.BINS[None, :]
    runs = cf.simulate(weights, offset, np.array([10.0]), np.array(["a"]), share=0.0, shock_days=20, sims=400, rng=np.random.default_rng(2))
    assert runs.sum(axis=1).max() == 10.0                             # a payment is never lost inside the 12 weeks here
    assert (runs[:, 0] > 0).any() and (runs[:, 1:].sum(axis=1) > 0).any()   # but it lands in different weeks


def test_scores_are_zero_error_for_a_perfect_forecast():
    actual = np.array([100.0, 50, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    items = [(actual, {"point": actual.copy(), "lo": actual - 1, "hi": actual + 1, "late": actual.copy()})] * 3
    s = cf.score(items)
    assert s["wape_weekly"] == 0 and s["bias"] == 0 and s["band_coverage"] == 1.0
    assert s["alert_recall"] == 1.0 and s["alert_precision"] == 1.0
