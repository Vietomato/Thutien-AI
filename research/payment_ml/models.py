"""The three ways to predict a delay: everyone pays on time, the customer's own quantiles, LightGBM quantiles.

All return a DataFrame with columns p25, p50, p75 in whole days. Delays are rounded half up so the comparison
matches what the system does with dates."""
import numpy as np
import pandas as pd

from .history import MIN_HISTORY, NAMES

NUMERIC = ["amount", "days_to_due", "due_month", "due_dow", "hist_n", "hist_mean", "hist_late_share",
           "hist_p25", "hist_p50", "hist_p75", "glob_p25", "glob_p50", "glob_p75"]
CATEGORICAL = ["cust_payment_terms", "business_code", "invoice_currency", "document_type"]


def _round_half_up(x):
    return np.floor(np.asarray(x, dtype=float) + 0.5)


def add_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    """Only what is known when the invoice is posted: amount, terms, how far away the due date is."""
    out = df.copy()
    out["days_to_due"] = (out["due"] - out["posting"]).dt.days
    out["due_month"] = out["due"].dt.month
    out["due_dow"] = out["due"].dt.dayofweek
    return out


def feature_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    return [c for c in NUMERIC if c in df.columns], [c for c in CATEGORICAL if c in df.columns]


def predict_on_time(df: pd.DataFrame) -> pd.DataFrame:
    """Baseline 1: every customer pays on the due date."""
    return pd.DataFrame(0.0, index=df.index, columns=list(NAMES))


def predict_customer_median(df: pd.DataFrame, min_history: int = MIN_HISTORY) -> pd.DataFrame:
    """Baseline 2: the customer's own P25/P50/P75 from earlier payments; with fewer than `min_history` paid
    invoices, everyone's; with no history at all, on time."""
    own = (df["hist_n"] >= min_history).to_numpy()
    out = pd.DataFrame(index=df.index, columns=list(NAMES), dtype=float)
    for name in NAMES:
        out[name] = np.where(own, df[f"hist_{name}"], df[f"glob_{name}"])
    return pd.DataFrame(_round_half_up(out.fillna(0.0)), index=df.index, columns=list(NAMES))


class LightGBMQuantiles:
    """Three LightGBM models, one per quantile (0.25, 0.5, 0.75)."""

    def __init__(self, n_estimators: int = 300, learning_rate: float = 0.05, num_leaves: int = 31,
                 min_child_samples: int = 50, random_state: int = 42):
        self.params = dict(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves,
                           min_child_samples=min_child_samples, random_state=random_state, n_jobs=1, verbose=-1)
        self.models = {}
        self.numeric: list[str] = []
        self.categorical: list[str] = []
        self.categories: dict[str, pd.Index] = {}

    def _matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        x = df[self.numeric + self.categorical].copy()
        for c in self.categorical:                      # categories seen in training; anything else becomes missing
            seen = self.categories[c]
            x[c] = x[c].where(x[c].isin(seen)).astype(pd.CategoricalDtype(seen))
        return x

    def fit(self, train: pd.DataFrame, numeric: list[str], categorical: list[str]) -> "LightGBMQuantiles":
        import lightgbm as lgb
        self.numeric, self.categorical = list(numeric), list(categorical)
        self.categories = {c: train[c].astype("category").cat.categories for c in self.categorical}
        x, y = self._matrix(train), train["delay"].to_numpy(dtype=float)
        for name, alpha in zip(NAMES, (0.25, 0.5, 0.75)):
            self.models[name] = lgb.LGBMRegressor(objective="quantile", alpha=alpha, **self.params).fit(x, y)
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        x = self._matrix(df)
        raw = np.column_stack([self.models[name].predict(x) for name in NAMES])
        raw = np.sort(raw, axis=1)                      # the three lines must never cross
        return pd.DataFrame(_round_half_up(raw), index=df.index, columns=list(NAMES))


def predict_delay_quantiles(model: LightGBMQuantiles, features: pd.DataFrame) -> pd.DataFrame:
    """The prediction function for a trained model. `features` needs the columns the model was trained on."""
    return model.predict(features)
