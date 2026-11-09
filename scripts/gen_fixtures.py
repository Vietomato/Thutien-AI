import json, random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "fixtures"
AS_OF = date(2026, 11, 9)
rng = random.Random(20261109)

CUSTOMERS = [
    ("C001", "Khach hang A", "a@example.test", [-2, 0, 1, 0, -1]),
    ("C002", "Khach hang B", "b@example.test", [-2, 0, 1, 3, 5, 8, 12, 20, 35]),
    ("C003", "Khach hang C", "c@example.test", [4, 6, 3, 9]),
    ("C004", "Khach hang D", "d@example.test", [10, 14, 7]),
    ("C005", "Khach hang E", "e@example.test", []),
]
invoices, payments, seed_inv = [], [], []
n = pay = 0


def add(cid, name, email, due, amount, paid_parts, dispute=False):
    global n, pay
    n += 1
    iid = f"INV-{n:03d}"
    remaining = amount - sum(a for _, a in paid_parts)
    invoices.append(dict(invoice_id=iid, customer_id=cid, display_name=name,
                         due_date=due.isoformat(), invoice_amount=amount,
                         remaining_amount=remaining, currency="VND",
                         dispute_status="disputed" if dispute else "none",
                         contact_email=email))
    plist = []
    for d, a in paid_parts:
        pay += 1
        payments.append(dict(payment_id=f"PAY-{pay:03d}", invoice_id=iid, customer_id=cid,
                             payment_date=d.isoformat(), amount=a))
        plist.append(dict(date=d.isoformat(), amount=a))
    seed_inv.append(dict(invoice_id=iid, customer_id=cid,
                         invoice_date=(due - timedelta(days=30)).isoformat(),
                         due_date=due.isoformat(), amount=amount,
                         dispute=dispute, payments=plist))


for cid, name, email, delays in CUSTOMERS:
    due = date(2026, 1, 15)
    for d in delays:
        amt = rng.randrange(10, 81) * 1_000_000
        add(cid, name, email, due, amt, [(due + timedelta(days=d), amt)])
        due += timedelta(days=25)

M = 1_000_000
add("C001", "Khach hang A", "a@example.test", AS_OF - timedelta(days=12), 50 * M, [])
add("C002", "Khach hang B", "b@example.test", AS_OF - timedelta(days=30), 120 * M, [])
add("C002", "Khach hang B", "b@example.test", AS_OF + timedelta(days=15), 40 * M, [])
due = AS_OF - timedelta(days=7)
add("C003", "Khach hang C", "c@example.test", due, 90 * M, [(due - timedelta(days=5), 30 * M)])
add("C004", "Khach hang D", "d@example.test", AS_OF - timedelta(days=20), 70 * M, [], dispute=True)
add("C005", "Khach hang E", "e@example.test", AS_OF + timedelta(days=20), 25 * M, [])

seed = dict(customers=[dict(customer_id=c, name=nm, email=e) for c, nm, e, _ in CUSTOMERS],
            invoices=seed_inv)
OUT.mkdir(exist_ok=True)
for fn, data in (("invoices.json", invoices), ("payments.json", payments), ("seed_data.json", seed)):
    (OUT / fn).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(invoices), "invoices,", len(payments), "payments")