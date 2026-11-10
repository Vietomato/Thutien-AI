import json
import os
import sys
import xmlrpc.client
from pathlib import Path

URL = os.getenv("ODOO_URL", "http://localhost:8069")
DB = os.getenv("ODOO_DB_NAME", "odoo")
USER = os.environ["ODOO_SETUP_USER"]
PWD = os.environ["ODOO_SETUP_PASSWORD"]

SEED = Path(__file__).resolve().parents[1] / "fixtures" / "seed_data.json"
data = json.loads(SEED.read_text(encoding="utf-8"))
limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, PWD, {})
if not uid:
    sys.exit("Login failed: check ODOO_SETUP_USER / ODOO_SETUP_PASSWORD / ODOO_DB_NAME")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)


def call(model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kwargs)


partner_ids = {}
for c in data["customers"]:
    found = call("res.partner", "search", [["ref", "=", c["customer_id"]]])
    if found:
        partner_ids[c["customer_id"]] = found[0]
    else:
        partner_ids[c["customer_id"]] = call(
            "res.partner", "create",
            {"name": c["name"], "ref": c["customer_id"], "email": c["email"]})

created = skipped = 0
for inv in data["invoices"][:limit]:
    exists = call("account.move", "search",
                  [["ref", "=", inv["invoice_id"]], ["move_type", "=", "out_invoice"]])
    if exists:
        skipped += 1
        continue
    move_id = call("account.move", "create", {
        "move_type": "out_invoice",
        "partner_id": partner_ids[inv["customer_id"]],
        "ref": inv["invoice_id"],
        "invoice_date": inv["invoice_date"],
        "invoice_date_due": inv["due_date"],
        "narration": "[DISPUTE]" if inv["dispute"] else False,
        "invoice_line_ids": [[0, 0, {
            "name": "Demo " + inv["invoice_id"],
            "quantity": 1,
            "price_unit": inv["amount"],
        }]],
    })
    call("account.move", "action_post", [move_id])
    for p in inv["payments"]:
        ctx = {"active_model": "account.move", "active_ids": [move_id]}
        wizard = call("account.payment.register", "create",
                      {"payment_date": p["date"], "amount": p["amount"]}, context=ctx)
        call("account.payment.register", "action_create_payments", [wizard], context=ctx)
    created += 1
    print("created", inv["invoice_id"])

print(f"done: created {created}, skipped (already existed) {skipped}")