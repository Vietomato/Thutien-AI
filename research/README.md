# T29: does machine learning beat the customer median? (optional, outside the P0 scope)

Question: can a model predict the payment delay (clear date minus due date, in days) better than the customer's own
median? The project only uses ML if it clearly wins, so this is a comparison, not a feature.

**Status:** the code and its tests are ready. **No result exists yet**: it needs the real CSV, and no number from the
project plan may be quoted as a result until this has been run on the file.

## Before using the data

1. Open https://www.kaggle.com/datasets/rajattomar132/payment-date-dataset and read the **License** and the data card.
   Do not share, commit or redistribute the file unless the license allows it.
2. Download the CSV and save it as `research/data/payment_date.csv`. The folder is ignored by git (see `.gitignore`).

## Run

    pip install -r research/requirements.txt
    python -m research.payment_ml.experiment --csv research/data/payment_date.csv

Optional: `--split-date 2020-01-01` (default: the date after 80% of the labelled invoices) and `--out research/results`.
It writes `audit.json` (what the file really contains), `metrics.json` and `report.md` to `research/results/` (ignored by git).

Tests (made-up data only, they do not need the CSV): `python -m pytest research/tests`

## What it does

- **Audit** (`data.audit`): row and column counts, empty columns, duplicates (exact copies versus a repeated `invoice_id`
  with different content), currencies, `isOpen` values, date ranges, invoices cleared before they were posted, customers
  with at least 5 paid invoices, delay percentiles. It reports; it assumes nothing.
- **Labels**: delay = clear date - due date. An invoice that is still open has **no** delay (it is not a 0).
- **No future information**: for each invoice, customer history uses only invoices cleared **strictly before its
  posting date**. The target and `clear_date` are never features.
- **Time split**: training = posted before the split date **and** already cleared before it (labels observable then);
  test = posted on or after it. Never a random split.
- **Three predictors** (whole days): everyone pays on time; the customer's own P25/P50/P75 (shared numbers when the
  customer has fewer than 5 paid invoices, on time if there is nothing at all); LightGBM quantile regression (0.25, 0.5, 0.75).
- **Measures**: MAE, RMSE, pinball loss at the three quantiles, coverage of P25-P75, also split by "5+ earlier paid
  invoices" and "fewer than 5".
- **Decision rule** (the project's proposed targets): use ML only if its MAE is at least 10% below the customer
  median **and** its pinball loss is lower at all three quantiles. Coverage between 40% and 60% is reported.

## Limits to state when presenting

- Open invoices are excluded, so late payers are under-represented in the test set; the report counts how many.
- Amounts are not converted between currencies.
- The data is not from a Vietnamese company. A model trained on it must **not** be transferred to Minh Phat or any other
  company by default.
- This does not backtest the weekly cash forecast (the separate P1 task DM-5).

## Weekly cash-flow backtest (does a better way to build the 12 weeks beat the current rule?)

```
python -m research.payment_ml.cashflow --csv research/data/payment_date.csv              # main comparison
python -m research.payment_ml.cashflow --csv research/data/payment_date.csv --ablation   # one ingredient at a time
```

At 23 forecast dates (Mondays 2019-06-03 to 2019-11-04) the open invoices are forecast week by week and compared with what they
really paid. The first 8 dates choose the settings, the other 15 score them. The baseline runs the production code
(`backend/app/analytics.py`) unchanged. USD invoices only; the file has no outgoings, so the shortfall-alert test uses a synthetic
outgoing level and does not separate the methods (every method scores 96-98% F1): do not quote it.

What the run showed (Kaggle data, 15 scored dates; written to `research/results/`, which is not committed):

| | WAPE weekly | WAPE cumulative 2 weeks |
|---|---|---|
| current rule (a date per invoice, summed) | 21.3% | 9.7% |
| expected value (amount x probability of paying that week), same history rule | 16.9% | 4.9% |
| expected value + shrinkage of own history toward everyone's | 16.6-16.7% | 4.6% |
| LightGBM quantiles inside the current rule | 15.2% | 7.7% |

- Almost all of the gain comes from allocating each invoice by probability instead of putting the whole amount on one date. Shrinkage
  adds about 0.2 points and recency weighting adds nothing on this data.
- The band between the current rule's early and late scenarios contained the real weekly receipts in about a third of the weeks. That is
  consistent with the product's wording: the three scenarios are a stress test, not an interval.
- A simulation (with invoices of one customer drawn together and a shared shift for all invoices) widened the band to cover 64% of weeks
  against a target of 80% on the later dates, so it is still not calibrated, and the band is wide (about the size of the receipts).
- LightGBM has the lowest weekly error but is trained on tens of thousands of invoices; Minh Phat has about 385. Do not conclude from this
  that it would win there.

Limits: one dataset, North American, not transferable to Minh Phat; the 15 scored dates overlap (each looks 12 weeks ahead), so they are
far fewer than 15 independent tests and no confidence interval is given; settings sit at the edge of the grid (k=2, no recency); only open
invoices are forecast, so weeks beyond about 6 are near zero for every method.
