"""T10: weekly receipts forecast (F4 engine). Pure functions: no database, no network, no clock.

For each open invoice with a prediction, its remaining_amount lands in the week of its predicted date,
once per scenario: P25 (early money), P50 (middle), P75 (late money). Weeks start on Monday; week 1 is
the week that contains as_of.

The three lines are one set of payment dates shifted early/middle/late. They are stress scenarios, not a
confidence interval, and a single week is not forced to satisfy P25 >= P50 >= P75.

Money that lands after the last week is not dropped: it is reported per scenario in out_of_horizon, so
(money inside the weeks) + (out_of_horizon) = (total remaining of predicted invoices), for every scenario.

Expected outgoings are entered by the accountant. Dated before week 1 starts (already late) they count
in week 1; dated after the last week they are reported in obligations_out_of_horizon.

gap_p75 = max(obligations - receipt_p75, 0). It says the late scenario brings in less than is going out
that week. It is not a cash balance: the opening balance is unknown."""
from datetime import date, timedelta

from pydantic import BaseModel, Field

from .contracts import Invoice, Prediction, Week

WEEKS = 12


class Obligation(BaseModel):
    description: str = Field(min_length=1)
    amount: int = Field(gt=0)
    due_date: date


class OutOfHorizon(BaseModel):
    p25: int
    p50: int
    p75: int


class Forecast(BaseModel):
    as_of_date: date
    weeks: list[Week]
    receipts_out_of_horizon: OutOfHorizon
    obligations_out_of_horizon: int


def week_start(day: date) -> date:
    """The Monday of the week that contains `day`."""
    return day - timedelta(days=day.weekday())


def forecast(invoices: list[Invoice], predictions: list[Prediction], obligations: list[Obligation],
             as_of: date, weeks: int = WEEKS) -> Forecast:
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    first = week_start(as_of)
    amount = {i.invoice_id: i.remaining_amount for i in invoices}

    receipts = {"p25": [0] * weeks, "p50": [0] * weeks, "p75": [0] * weeks}
    beyond = {"p25": 0, "p50": 0, "p75": 0}
    for p in predictions:
        if p.invoice_id not in amount:
            raise ValueError(f"prediction for unknown invoice {p.invoice_id}")
        for key, day in (("p25", p.predicted_date_p25), ("p50", p.predicted_date_p50),
                         ("p75", p.predicted_date_p75)):
            idx = max(0, (day - first).days // 7)
            if idx < weeks:
                receipts[key][idx] += amount[p.invoice_id]
            else:
                beyond[key] += amount[p.invoice_id]

    outgoing = [0] * weeks
    obligations_beyond = 0
    for o in obligations:
        idx = max(0, (o.due_date - first).days // 7)
        if idx < weeks:
            outgoing[idx] += o.amount
        else:
            obligations_beyond += o.amount

    return Forecast(
        as_of_date=as_of,
        weeks=[Week(week_start=first + timedelta(days=7 * i),
                    receipt_p25=receipts["p25"][i], receipt_p50=receipts["p50"][i],
                    receipt_p75=receipts["p75"][i], obligations=outgoing[i],
                    gap_p75=max(outgoing[i] - receipts["p75"][i], 0))
               for i in range(weeks)],
        receipts_out_of_horizon=OutOfHorizon(**beyond),
        obligations_out_of_horizon=obligations_beyond,
    )
