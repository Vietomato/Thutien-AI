from datetime import date
from decimal import Decimal

from app.f3.priority import CompletedInvoice, PriorityInvoice, rank_priority

AS_OF = date(2026, 11, 9)


def invoice(invoice_id: str, customer: str, amount: str, due: date, **kwargs):
    return PriorityInvoice(
        invoice_id=invoice_id,
        customer_id=customer,
        display_name=customer,
        due_date=due,
        invoice_amount=Decimal(amount),
        remaining_amount=Decimal(kwargs.pop("remaining", amount)),
        contact_email=kwargs.pop("contact_email", "ar@example.test"),
        **kwargs,
    )


def test_priority_score_matches_contract_example():
    history = [
        CompletedInvoice("h1", "A", date(2026, 10, 1), date(2026, 10, 3)),
        CompletedInvoice("h2", "A", date(2026, 10, 1), date(2026, 10, 1)),
        CompletedInvoice("h3", "B", date(2026, 10, 1), date(2026, 10, 2)),
    ]
    rows = rank_priority(
        [
            invoice("A-open", "A", "80000000", date(2026, 11, 5)),
            invoice("B-open", "B", "30000000", date(2026, 11, 7)),
        ],
        history,
        as_of_date=AS_OF,
    )
    assert [row["invoice_id"] for row in rows] == ["A-open", "B-open"]
    assert rows[0]["priority_score"] == Decimal("160000000")
    assert rows[1]["priority_score"] == Decimal("60000000")


def test_eligibility_uses_remaining_balance_and_explains_holds():
    rows = rank_priority(
        [
            invoice("partial", "A", "100", date(2026, 11, 5), remaining="80"),
            invoice("dispute", "A", "100", date(2026, 11, 5), dispute_status="disputed"),
            invoice("no-contact", "A", "100", date(2026, 11, 5), contact_email=None),
            invoice("paid", "A", "0", date(2026, 11, 5), remaining="0"),
        ],
        [],
        as_of_date=AS_OF,
    )
    by_id = {row["invoice_id"]: row for row in rows}
    assert by_id["partial"]["priority_score"] == Decimal("160")
    assert by_id["partial"]["eligible_for_reminder"] is True
    assert by_id["dispute"]["hold_reasons"] == ["disputed"]
    assert by_id["no-contact"]["hold_reasons"] == ["missing_contact"]
    assert "no_remaining_balance" in by_id["paid"]["hold_reasons"]
    assert by_id["partial"]["late_rate_source"] == "assumed_0.5_no_history"


def test_ties_are_deterministic_and_future_history_is_ignored():
    rows = rank_priority(
        [
            invoice("z", "unknown", "100", date(2026, 11, 5)),
            invoice("a", "unknown", "100", date(2026, 11, 5)),
        ],
        [CompletedInvoice("future", "unknown", AS_OF, date(2026, 11, 10))],
        as_of_date=AS_OF,
    )
    assert [row["invoice_id"] for row in rows] == ["a", "z"]
    assert all(row["late_rate_source"] == "assumed_0.5_no_history" for row in rows)
