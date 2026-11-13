"""Weekly cash-flow backtest: can the 12-week receipts be built better than the current rule?

    python -m research.payment_ml.cashflow --csv research/data/payment_date.csv

At every forecast date t (a Monday) the question is the one the product answers: "of the invoices open today, how much
money arrives in each of the next 12 weeks?". Only what was known at t is used: payments cleared strictly before t. The truth
is what those same invoices actually paid, week by week (every open invoice of the chosen dates is cleared in the file).

Methods compared
  current       the production code (backend/app/analytics.py): each invoice gets P25/P50/P75 payment dates, receipts are summed per week.
  expected      the invoice's delay distribution (own history shrunk toward everyone's, recent payments weighted more, conditioned on
                "not paid yet") -> expected receipts = amount x probability of paying that week.
  simulation    the same distributions, sampled thousands of times -> a real band for weekly receipts and P(shortfall).
  lightgbm      the T29 quantile model (re-fitted at each date) used inside the current week-building rule.

Settings (shrinkage strength, recency half-life, how much invoices of one customer move together) are chosen on the EARLIER
forecast dates and scored on the LATER ones. Money is USD only (the file mixes USD and CAD without a rate). Shortfall alerts need
outgoings, which this file does not have: a synthetic weekly outgoing level is used (see report), the same for every method."""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, history, models

WEEKS = 12
BMIN, BMAX = -120, 260                       # delay values (days) represented in the histograms
NB = BMAX - BMIN + 1
BINS = np.arange(NB) + BMIN
MATURITY_DAYS = 60                           # same rule as the T29 training set
EVAL_WEEKS = 6                               # band and alerts are scored on the first 6 weeks: later weeks are ~0 for every method
ALPHAS = (0.6, 0.8, 1.0, 1.2)                # synthetic weekly outgoing level = alpha x the mean weekly receipts of that window


# ---------------------------------------------------------------- data at a forecast date

@dataclass
class Origin:
    t: pd.Timestamp
    open: pd.DataFrame          # invoices open at t
    known: pd.DataFrame         # invoices cleared strictly before t: their delays are known at t
    actual: np.ndarray          # (12,) what the open invoices really paid per week


def usd_frame(raw: pd.DataFrame) -> pd.DataFrame:
    df, _ = data.prepare(raw)
    df = df[(df["invoice_currency"] == "USD") & (df["amount"] > 0)].reset_index(drop=True)
    return models.add_basic_features(history.add_global_prior(history.add_customer_history(df)))


def make_origin(df: pd.DataFrame, t: pd.Timestamp) -> Origin:
    known = df[df["delay"].notna() & (df["clear"] < t)]
    open_ = df[(df["posting"] <= t) & (df["clear"].isna() | (df["clear"] >= t))].copy()
    if open_["clear"].isna().any():
        raise ValueError(f"{t.date()}: some open invoices never clear in the file, the truth is unknown; pick an earlier date")
    week = ((open_["clear"] - t).dt.days // 7).to_numpy()
    inside = (week >= 0) & (week < WEEKS)
    actual = np.zeros(WEEKS)
    np.add.at(actual, week[inside], open_["amount"].to_numpy()[inside])
    return Origin(t=t, open=open_.reset_index(drop=True), known=known.reset_index(drop=True), actual=actual)


# ---------------------------------------------------------------- delay distributions

def pools(known: pd.DataFrame, t: pd.Timestamp, half_life: float | None):
    """Histogram of known delays, everyone's and per customer; recent payments weigh more when `half_life` (days) is set."""
    idx = np.clip(known["delay"].to_numpy().astype(int) - BMIN, 0, NB - 1)
    age = (t - known["clear"]).dt.days.to_numpy()
    w = np.ones(len(known)) if not half_life else 0.5 ** (age / half_life)
    glob = np.bincount(idx, weights=w, minlength=NB)
    per_customer = {}
    codes, uniq = pd.factorize(known["customer"])
    for c in range(len(uniq)):
        sel = codes == c
        per_customer[uniq[c]] = (np.bincount(idx[sel], weights=w[sel], minlength=NB), float(w[sel].sum()))
    return glob, per_customer


def distributions(open_: pd.DataFrame, t: pd.Timestamp, glob, per_customer, k: float):
    """Row i: probability of each delay for invoice i.
    lambda = n / (n + k): the customer's own history counts for n and the shared history for k (shrinkage, no hard cut at 5).
    Then conditioned on 'not paid yet': an invoice that is `overdue` days past due can only have a delay >= overdue.
    If nothing in the history is that late, the typical delay is counted from today instead (as the production code does).
    Returns weights (n, NB), the day offset from t of each delay (n, NB) and which rows used the fallback."""
    n = len(open_)
    shared = glob / glob.sum()
    weights = np.tile(shared, (n, 1))
    customers = open_["customer"].to_numpy()
    for i in range(n):
        hist = per_customer.get(customers[i])
        if hist is not None and hist[1] > 0:
            lam = hist[1] / (hist[1] + k)
            weights[i] = (1 - lam) * shared + lam * hist[0] / hist[0].sum()
    overdue = (t - open_["due"]).dt.days.to_numpy()
    kept = weights * (BINS[None, :] >= overdue[:, None])
    mass = kept.sum(axis=1)
    fallback = mass < 1e-9
    kept[~fallback] /= mass[~fallback, None]
    kept[fallback] = weights[fallback]
    due_offset = (open_["due"] - t).dt.days.to_numpy()
    offset = np.where(fallback[:, None], np.maximum(1, BINS[None, :]), due_offset[:, None] + BINS[None, :])
    return kept, offset, fallback


def week_probabilities(weights: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """(n, 12): probability that invoice i pays in week w (mass beyond week 12 is simply not counted)."""
    week = offset // 7
    return np.stack([(weights * (week == w)).sum(axis=1) for w in range(WEEKS)], axis=1)


def simulate(weights, offset, amount, customers, share: float, shock_days: float, sims: int, rng) -> np.ndarray:
    """(sims, 12) weekly receipts. `share` = probability that an invoice takes the same random draw as the other invoices of
    its customer (customers often pay several invoices together); 0 = every invoice independent. `shock_days` is the standard
    deviation of a delay shift shared by ALL invoices in one simulation (whole periods in which everybody pays later or sooner)."""
    n = len(amount)
    cdf = np.cumsum(weights, axis=1)
    cdf[:, -1] = 1.0
    codes, uniq = pd.factorize(customers)
    u = np.where(rng.random((sims, n)) < share, rng.random((sims, len(uniq)))[:, codes], rng.random((sims, n)))
    chosen = np.empty((sims, n), dtype=np.int32)
    for i in range(n):
        chosen[:, i] = offset[i, np.minimum(np.searchsorted(cdf[i], u[:, i]), NB - 1)]
    shift = np.round(rng.normal(0.0, shock_days, size=(sims, 1))).astype(np.int32) if shock_days else 0
    chosen = np.maximum(chosen + shift, 0) // 7
    out = np.zeros((sims, WEEKS))
    for w in range(WEEKS):
        out[:, w] = ((chosen == w) * amount[None, :]).sum(axis=1)
    return out


# ---------------------------------------------------------------- the methods

def method_current(o: Origin) -> dict:
    """The production rule, run as it is."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app import analytics, contracts
    invoices = [contracts.Invoice(invoice_id=str(i), customer_id=str(c), display_name=str(c), due_date=d.date(),
                                  invoice_amount=int(round(a)), remaining_amount=int(round(a)))
                for i, (c, d, a) in enumerate(zip(o.open["customer"], o.open["due"], o.open["amount"]))]
    delays = [(str(c), int(x)) for c, x in zip(o.known["customer"], o.known["delay"])]
    weeks = analytics.forecast(invoices, analytics.predict(invoices, delays, o.t.date()), [], o.t.date(), WEEKS)
    early = np.array([w.receipt_p25 for w in weeks], float)
    mid = np.array([w.receipt_p50 for w in weeks], float)
    late = np.array([w.receipt_p75 for w in weeks], float)
    return {"point": mid, "lo": np.minimum(early, late), "hi": np.maximum(early, late), "late": late}


def method_expected(o: Origin, k: float, half_life: float | None) -> dict:
    glob, per_customer = pools(o.known, o.t, half_life)
    weights, offset, _ = distributions(o.open, o.t, glob, per_customer, k)
    expected = (week_probabilities(weights, offset) * o.open["amount"].to_numpy()[:, None]).sum(axis=0)
    return {"point": expected, "late": expected, "_dist": (weights, offset)}


def method_expected_hard_cut(o: Origin, min_history: int = 5) -> dict:
    """Same expected-value weeks, but with the production rule for choosing the history: the customer's own delays when it has
    at least `min_history` paid invoices, otherwise everyone's (no shrinkage)."""
    glob, per_customer = pools(o.known, o.t, None)
    shared = glob / glob.sum()
    weights = np.tile(shared, (len(o.open), 1))
    for i, customer in enumerate(o.open["customer"].to_numpy()):
        hist = per_customer.get(customer)
        if hist is not None and hist[1] >= min_history:
            weights[i] = hist[0] / hist[0].sum()
    overdue = (o.t - o.open["due"]).dt.days.to_numpy()
    kept = weights * (BINS[None, :] >= overdue[:, None])
    mass = kept.sum(axis=1)
    fallback = mass < 1e-9
    kept[~fallback] /= mass[~fallback, None]
    kept[fallback] = weights[fallback]
    due_offset = (o.open["due"] - o.t).dt.days.to_numpy()
    offset = np.where(fallback[:, None], np.maximum(1, BINS[None, :]), due_offset[:, None] + BINS[None, :])
    expected = (week_probabilities(kept, offset) * o.open["amount"].to_numpy()[:, None]).sum(axis=0)
    return {"point": expected, "late": expected}


def method_simulation(o: Origin, k: float, half_life: float | None, share: float, shock: float, sims: int, seed: int,
                      cached: dict | None = None) -> dict:
    base = cached or method_expected(o, k, half_life)
    weights, offset = base["_dist"]
    rng = np.random.default_rng(seed)
    runs = simulate(weights, offset, o.open["amount"].to_numpy(), o.open["customer"].to_numpy(), share, shock, sims, rng)
    return {"point": base["point"], "lo": np.quantile(runs, 0.1, axis=0), "hi": np.quantile(runs, 0.9, axis=0),
            "late": np.quantile(runs, 0.5, axis=0), "runs": runs}


def refresh_history(open_: pd.DataFrame, known: pd.DataFrame) -> pd.DataFrame:
    """Customer history as it stands at t (the T29 features were frozen at each invoice's posting date)."""
    out = open_.copy()
    by = known.groupby("customer")["delay"]
    stats = pd.DataFrame({"hist_n": by.size(), "hist_mean": by.mean(), "hist_late_share": by.apply(lambda s: (s > 0).mean()),
                          "hist_p25": by.quantile(0.25), "hist_p50": by.quantile(0.5), "hist_p75": by.quantile(0.75)})
    out = out.drop(columns=[c for c in stats.columns if c in out.columns]).merge(stats, left_on="customer", right_index=True, how="left")
    out["hist_n"] = out["hist_n"].fillna(0).astype(int)
    for name, q in zip(("p25", "p50", "p75"), (0.25, 0.5, 0.75)):
        out[f"glob_{name}"] = known["delay"].quantile(q)
    return out


def method_lightgbm(o: Origin, df: pd.DataFrame, numeric, categorical) -> dict:
    train = df[df["delay"].notna() & (df["posting"] < o.t) & (df["clear"] < o.t) & (df["due"] <= o.t - pd.Timedelta(days=MATURITY_DAYS))]
    model = models.LightGBMQuantiles().fit(train, numeric, categorical)
    open_ = refresh_history(o.open, o.known)
    q = model.predict(open_)
    due_offset = (open_["due"] - o.t).dt.days.to_numpy()
    amount = open_["amount"].to_numpy()
    receipts = {}
    for name in ("p25", "p50", "p75"):
        offset = np.maximum(due_offset + q[name].to_numpy(), 0)
        week = (offset // 7).astype(int)
        arr = np.zeros(WEEKS)
        inside = week < WEEKS
        np.add.at(arr, week[inside], amount[inside])
        receipts[name] = arr
    return {"point": receipts["p50"], "lo": np.minimum(receipts["p25"], receipts["p75"]),
            "hi": np.maximum(receipts["p25"], receipts["p75"]), "late": receipts["p75"]}


# ---------------------------------------------------------------- scoring

def score(items: list[tuple[np.ndarray, dict]], shortfall_probability: bool = False) -> dict:
    """items: (actual weekly receipts, forecast) per forecast date."""
    A = np.array([a for a, _ in items])
    P = np.array([f["point"] for _, f in items])
    total = A.sum()
    out = {"dates": len(items), "wape_weekly": float(np.abs(P - A).sum() / total), "bias": float((P - A).sum() / total)}
    for k in (2, 4, 6):
        ca, cp = A[:, :k].sum(axis=1), P[:, :k].sum(axis=1)
        out[f"wape_cumulative_{k}w"] = float(np.abs(cp - ca).sum() / ca.sum())
    if "lo" in items[0][1]:
        lo, hi = np.array([f["lo"] for _, f in items])[:, :EVAL_WEEKS], np.array([f["hi"] for _, f in items])[:, :EVAL_WEEKS]
        a6 = A[:, :EVAL_WEEKS]
        out["band_coverage"] = float(((a6 >= lo) & (a6 <= hi)).mean())
        out["band_width_vs_receipts"] = float((hi - lo).sum() / a6.sum())
    tp = fp = fn = tn = 0
    for alpha in ALPHAS:
        for a, f in items:
            level = alpha * a[:EVAL_WEEKS].mean()
            truth = a[:EVAL_WEEKS] < level
            if shortfall_probability:
                pred = (f["runs"][:, :EVAL_WEEKS] < level).mean(axis=0) >= 0.5
            else:
                pred = f["late"][:EVAL_WEEKS] < level
            tp += int((truth & pred).sum()); fp += int((~truth & pred).sum())
            fn += int((truth & ~pred).sum()); tn += int((~truth & ~pred).sum())
    out["alert_precision"] = tp / (tp + fp) if tp + fp else float("nan")
    out["alert_recall"] = tp / (tp + fn) if tp + fn else float("nan")
    p, r = out["alert_precision"], out["alert_recall"]
    out["alert_f1"] = 2 * p * r / (p + r) if p == p and r == r and p + r else float("nan")
    return out


# ---------------------------------------------------------------- the experiment

def run(csv_path, first="2019-06-03", last="2019-11-04", step_days=7, tune_dates=8, sims=300, seed=7) -> dict:
    df = usd_frame(data.load_csv(csv_path))
    numeric, categorical = models.feature_columns(df)
    dates = list(pd.date_range(first, last, freq=f"{step_days}D"))
    origins = [make_origin(df, t) for t in dates]
    tune, test = origins[:tune_dates], origins[tune_dates:]

    best = None
    for k in (2, 5, 10, 20):
        for half_life in (None, 120, 365):
            items = [(o.actual, method_expected(o, k, half_life)) for o in tune]
            w = score(items)["wape_weekly"]
            if best is None or w < best[0]:
                best = (w, k, half_life)
    _, k, half_life = best

    best_sim = None
    tune_bases = [method_expected(o, k, half_life) for o in tune]
    for share in (0.0, 0.5, 1.0):
        for shock in (0, 2, 4, 7, 10):
            items = [(o.actual, method_simulation(o, k, half_life, share, shock, 200, seed, b)) for o, b in zip(tune, tune_bases)]
            s = score(items, shortfall_probability=True)
            gap = abs(s["band_coverage"] - 0.8)
            if best_sim is None or (gap, s["band_width_vs_receipts"]) < best_sim[0]:
                best_sim = ((gap, s["band_width_vs_receipts"]), share, shock)
    _, share, shock = best_sim

    results = {"current (production code)": [], "lightgbm in the current rule": [], "expected value": [],
               "simulation, invoices independent": [], f"simulation, tuned (share={share}, shock={shock}d)": []}
    for o in test:
        results["current (production code)"].append((o.actual, method_current(o)))
        results["lightgbm in the current rule"].append((o.actual, method_lightgbm(o, df, numeric, categorical)))
        base = method_expected(o, k, half_life)
        results["expected value"].append((o.actual, base))
        results["simulation, invoices independent"].append((o.actual, method_simulation(o, k, half_life, 0.0, 0, sims, seed, base)))
        results[f"simulation, tuned (share={share}, shock={shock}d)"].append((o.actual, method_simulation(o, k, half_life, share, shock, sims, seed, base)))
    scores = {name: score(items, shortfall_probability=name.startswith("simulation")) for name, items in results.items()}
    return {"first_date": str(dates[0].date()), "last_date": str(dates[-1].date()), "step_days": step_days,
            "tuning_dates": len(tune), "test_dates": len(test), "chosen": {"k": k, "half_life_days": half_life, "share": share, "shock_days": shock},
            "mean_open_invoices": float(np.mean([len(o.open) for o in origins])),
            "mean_weekly_receipts": float(np.mean([o.actual.mean() for o in origins])), "scores": scores}


def ablation(csv_path, first="2019-06-03", last="2019-11-04", step_days=7, tune_dates=8) -> dict:
    """Which ingredient of the new method pays for the gain? Each variant changes one thing, on the same later dates."""
    df = usd_frame(data.load_csv(csv_path))
    dates = list(pd.date_range(first, last, freq=f"{step_days}D"))
    test = [make_origin(df, t) for t in dates][tune_dates:]
    variants = {"current rule (production code)": lambda o: method_current(o),
                "expected value, hard cut at 5 paid invoices": lambda o: method_expected_hard_cut(o)}
    for k in (1, 2, 5, 10, 20):
        variants[f"expected value, shrinkage k={k}"] = lambda o, k=k: method_expected(o, k, None)
    variants["expected value, everyone's history only"] = lambda o: method_expected(o, 1e9, None)
    for half_life in (60, 120, 365):
        variants[f"expected value, k=2, recency half-life {half_life} days"] = lambda o, h=half_life: method_expected(o, 2, h)
    rows = {}
    for name, make in variants.items():
        s = score([(o.actual, make(o)) for o in test])
        rows[name] = {key: s[key] for key in ("wape_weekly", "bias", "wape_cumulative_2w", "wape_cumulative_4w")}
    return {"test_dates": len(test), "rows": rows}


def ablation_markdown(r: dict) -> str:
    out = ["# Where does the gain come from?", "", f"Same {r['test_dates']} later forecast dates as the main table; money is USD only.", "",
           "| Variant | WAPE weekly | Bias | WAPE cum. 2w | WAPE cum. 4w |", "|---|---|---|---|---|"]
    for name, s in r["rows"].items():
        out.append(f"| {name} | {s['wape_weekly']:.1%} | {s['bias']:+.1%} | {s['wape_cumulative_2w']:.1%} | {s['wape_cumulative_4w']:.1%} |")
    return "\n".join(out) + "\n"


def report_markdown(r: dict) -> str:
    cols = [("wape_weekly", "WAPE weekly"), ("bias", "Bias"), ("wape_cumulative_2w", "WAPE cum. 2w"), ("wape_cumulative_6w", "WAPE cum. 6w"),
            ("band_coverage", "Band coverage"), ("band_width_vs_receipts", "Band width / receipts"),
            ("alert_precision", "Alert precision"), ("alert_recall", "Alert recall"), ("alert_f1", "Alert F1")]
    out = ["# Weekly cash-flow backtest", "",
           f"Forecast dates {r['first_date']} to {r['last_date']} every {r['step_days']} days; the first {r['tuning_dates']} choose the settings, "
           f"the other {r['test_dates']} score them. About {r['mean_open_invoices']:.0f} open USD invoices per date.",
           f"Chosen settings: shrinkage k={r['chosen']['k']}, recency half-life {r['chosen']['half_life_days']} days, customer share {r['chosen']['share']}, common shock {r['chosen']['shock_days']} days.", "",
           "| Method | " + " | ".join(label for _, label in cols) + " |", "|---|" + "---|" * len(cols)]
    for name, s in r["scores"].items():
        cells = []
        for key, _ in cols:
            v = s.get(key)
            cells.append("n/a" if v is None or v != v else f"{v:+.1%}" if key == "bias" else f"{v:.1%}")
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    out += ["", "How to read it", "",
            "- WAPE: sum of absolute errors / sum of actual receipts (lower is better). Bias: positive = forecast too high.",
            "- Band coverage and alerts are scored on the first 6 weeks (later weeks are about 0 for every method, because only open invoices are forecast).",
            "- Band coverage: share of weeks where the real receipts fall inside the method's band. The current rule's band is its early-to-late "
            "scenario range; the simulation's band is its 10th to 90th percentile (target 80%). A band that is wide covers easily: read it with the width.",
            "- Alerts need outgoings, which the file lacks: a synthetic weekly level (0.6, 0.8, 1.0, 1.2 x that window's mean receipts) is used "
            "for every method, so this compares methods against each other and says nothing about a real company's cash position. "
            "The simulation alerts when P(receipts < level) >= 50%; the others when their late-scenario receipts are below the level.",
            "- USD invoices only. North American data: nothing here transfers to Minh Phat by default."]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", default="research/results")
    parser.add_argument("--sims", type=int, default=300)
    parser.add_argument("--ablation", action="store_true", help="change one ingredient at a time instead of the main comparison")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.ablation:
        result = ablation(args.csv)
        (out / "cashflow_ablation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (out / "cashflow_ablation.md").write_text(ablation_markdown(result), encoding="utf-8")
        print(ablation_markdown(result))
        return
    result = run(args.csv, sims=args.sims)
    (out / "cashflow.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (out / "cashflow.md").write_text(report_markdown(result), encoding="utf-8")
    print(report_markdown(result))


if __name__ == "__main__":
    main()
