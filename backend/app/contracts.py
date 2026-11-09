from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel


class Invoice(BaseModel):
    invoice_id: str
    customer_id: str
    display_name: str
    due_date: date
    invoice_amount: int
    remaining_amount: int
    currency: Literal["VND"] = "VND"
    dispute_status: Literal["none", "disputed"] = "none"
    contact_email: Optional[str] = None


class Payment(BaseModel):
    payment_id: str
    invoice_id: str
    customer_id: str
    payment_date: date
    amount: int


class Prediction(BaseModel):
    invoice_id: str
    as_of_date: date
    predicted_date_p25: date
    predicted_date_p50: date
    predicted_date_p75: date
    history_count: int
    method: Literal["customer_median", "global_median", "no_history"]
    low_history: bool
    overdue_adjusted: bool


class Week(BaseModel):
    week_start: date
    receipt_p25: int
    receipt_p50: int
    receipt_p75: int
    obligations: int
    gap_p75: int