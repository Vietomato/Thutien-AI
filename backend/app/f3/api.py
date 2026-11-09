from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .priority import CompletedInvoice, PriorityInvoice, rank_priority

router = APIRouter(prefix="/api/f3", tags=["F3 collections priority"])


@router.get("/priority")
def get_priority(request: Request) -> dict[str, Any]:
    """Rank invoices supplied by the live-data adapter; never silently fall back to mock data."""
    authorize: Callable[[Request, str], bool] | None = getattr(
        request.app.state, "f3_authorize_detail", None
    )
    if authorize is None:
        raise HTTPException(
            status_code=503,
            detail="F3 authorization is not configured; refusing to expose invoice details.",
        )
    if not authorize(request, "f3:read_detail"):
        raise HTTPException(status_code=403, detail="You are not allowed to view invoice details.")

    provider: Callable[[], Mapping[str, Any]] | None = getattr(
        request.app.state, "f3_priority_provider", None
    )
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="F3 live data provider is not configured; refusing to return mock data.",
        )

    data = provider()
    as_of_date = date.fromisoformat(data["as_of_date"])
    invoices = [
        PriorityInvoice(
            **{
                **row,
                "due_date": date.fromisoformat(row["due_date"]),
                "invoice_amount": Decimal(str(row["invoice_amount"])),
                "remaining_amount": Decimal(str(row["remaining_amount"])),
            }
        )
        for row in data["invoices"]
    ]
    history = [
        CompletedInvoice(
            **{
                **row,
                "due_date": date.fromisoformat(row["due_date"]),
                "completed_date": date.fromisoformat(row["completed_date"]),
            }
        )
        for row in data["completed_invoice_history"]
    ]
    return {
        "as_of_date": as_of_date.isoformat(),
        "data_mode": data.get("data_mode", "live"),
        "items": rank_priority(
            invoices,
            history,
            as_of_date=as_of_date,
            predictions=data.get("predictions", {}),
            active_draft_invoice_ids=set(data.get("active_draft_invoice_ids", [])),
        ),
    }
