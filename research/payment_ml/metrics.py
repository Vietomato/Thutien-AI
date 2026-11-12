"""Error measures for the payment-delay prediction (all in days)."""
import numpy as np


def mae(y, p) -> float:
    """Mean absolute error: how many days the prediction is off on average."""
    return float(np.mean(np.abs(np.asarray(y, dtype=float) - np.asarray(p, dtype=float))))


def rmse(y, p) -> float:
    return float(np.sqrt(np.mean((np.asarray(y, dtype=float) - np.asarray(p, dtype=float)) ** 2)))


def pinball(y, p, q: float) -> float:
    """Quantile loss: q*(y-p) when the real value is above the prediction, (1-q)*(p-y) when below."""
    d = np.asarray(y, dtype=float) - np.asarray(p, dtype=float)
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def coverage(y, lo, hi) -> float:
    """Share of invoices whose real delay falls inside [lo, hi] (P25..P75, so about 0.5 is expected)."""
    y = np.asarray(y, dtype=float)
    return float(np.mean((y >= np.asarray(lo, dtype=float)) & (y <= np.asarray(hi, dtype=float))))


def evaluate(y, pred) -> dict:
    """`pred` has columns p25, p50, p75."""
    return {
        "n": int(len(y)),
        "mae": mae(y, pred["p50"]),
        "rmse": rmse(y, pred["p50"]),
        "pinball_p25": pinball(y, pred["p25"], 0.25),
        "pinball_p50": pinball(y, pred["p50"], 0.5),
        "pinball_p75": pinball(y, pred["p75"], 0.75),
        "coverage_p25_p75": coverage(y, pred["p25"], pred["p75"]),
    }
