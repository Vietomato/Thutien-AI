"""Nạp dữ liệu demo vào Odoo theo lô (nhanh hơn seed_odoo.py khoảng 5 đến 8 lần).

    python scripts/seed_odoo_fast.py --limit 20     # thử với 20 hóa đơn đầu, kiểm tra trên Odoo rồi mới chạy đủ
    python scripts/seed_odoo_fast.py                 # nạp tất cả
    python scripts/seed_odoo_fast.py --dry-run       # chỉ in kế hoạch, không ghi gì vào Odoo
    python scripts/seed_odoo_fast.py --seed duong/dan/seed_data.json --batch 100
    python scripts/seed_odoo_fast.py --delay 1.0       # giãn nhịp nếu Odoo.com báo HTTP 429 (gọi quá nhanh)

Cách làm: tạo khách theo lô, tạo hóa đơn theo lô rồi xác nhận cả lô, trả đủ thì nhóm theo ngày thanh toán
(mỗi ngày một lần gọi), trả góp thì làm riêng từng hóa đơn. Chạy lại an toàn: hóa đơn đã có (theo mã ref) không bị
tạo lại, hóa đơn còn thiếu thanh toán thì được bổ sung.
Script này GHI vào Odoo bằng tài khoản quản trị. Chỉ dùng cho database demo. Đọc ODOO_URL, ODOO_DB, ODOO_EMAIL,
ODOO_API_KEY từ .env như seed_odoo.py.
"""
import json
import os
import sys
import time
import xmlrpc.client
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_conn = {}


def load_env():
    for p in [ROOT / ".env", ROOT / "backend" / ".env"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def connect():
    url = (os.getenv("ODOO_URL") or "http://localhost:8069").rstrip("/")
    if url.endswith("/odoo"):
        url = url[:-5]
    db = os.getenv("ODOO_DB") or os.getenv("ODOO_DB_NAME", "odoo")
    user = os.getenv("ODOO_EMAIL") or os.getenv("ODOO_SETUP_USER", "")
    pwd = os.getenv("ODOO_API_KEY") or os.getenv("ODOO_SETUP_PASSWORD", "")
    if not user or not pwd:
        sys.exit("Cần cấu hình ODOO_EMAIL và ODOO_API_KEY (hoặc ODOO_SETUP_USER / ODOO_SETUP_PASSWORD) trong .env")
    print(f"Kết nối Odoo tại {url} (database {db}, user {user})...")
    try:
        uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True).authenticate(db, user, pwd, {})
    except Exception as e:
        sys.exit(f"Lỗi kết nối Odoo: {e}")
    if not uid:
        sys.exit("Đăng nhập thất bại: kiểm tra ODOO_EMAIL, ODOO_API_KEY, ODOO_DB")
    _conn.update(models=xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True), db=db, uid=uid, pwd=pwd)


DELAY = 0.4        # giây nghỉ giữa hai lệnh gọi, để Odoo.com không chặn vì gọi quá nhanh (HTTP 429)


def call(model, method, *args, **kwargs):
    """Gọi Odoo. Bị HTTP 429 (Odoo.com giới hạn tốc độ) thì chờ rồi thử lại; mỗi lần bị chặn thì tự giãn nhịp thêm.
    Chỉ thử lại với 429, vì 429 nghĩa là Odoo chưa xử lý yêu cầu nên thử lại không tạo trùng."""
    global DELAY
    for attempt in range(8):
        if DELAY:
            time.sleep(DELAY)
        try:
            return _conn["models"].execute_kw(_conn["db"], _conn["uid"], _conn["pwd"], model, method, list(args), kwargs)
        except xmlrpc.client.ProtocolError as e:
            if e.errcode != 429:
                raise
            try:
                wait = int(e.headers.get("Retry-After", 0))
            except (TypeError, ValueError, AttributeError):
                wait = 0
            wait = wait or min(60, 5 * 2 ** attempt)
            DELAY = min(DELAY * 1.5 + 0.2, 3.0)
            print(f"  Odoo giới hạn tốc độ (429), chờ {wait}s rồi thử lại (nhịp mới {DELAY:.1f}s/lệnh)...")
            time.sleep(wait)
    raise RuntimeError("Odoo vẫn trả 429 sau nhiều lần thử, hãy chờ vài phút rồi chạy lại")


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def as_ids(res, expected):
    """create với danh sách trả về danh sách id; bản Odoo cũ có thể trả một số nguyên."""
    ids = res if isinstance(res, list) else [res]
    if len(ids) != expected:
        raise RuntimeError(f"Odoo trả {len(ids)} id, cần {expected}")
    return ids


def pending_payments(inv, ex):
    """Các khoản thanh toán còn phải tạo. ex là hóa đơn đã có trong Odoo (hoặc None nếu mới)."""
    pays = sorted(inv["payments"], key=lambda p: p["date"])
    if ex is None:
        return pays
    paid = ex["amount_total"] - ex["amount_residual"]
    cum, out = 0, []
    for p in pays:
        cum += p["amount"]
        if cum > paid + 0.5:
            out.append(p)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arg = lambda name, default=None: argv[argv.index(name) + 1] if name in argv else default
    limit = int(arg("--limit", 0)) or None
    batch = int(arg("--batch", 100))
    dry = "--dry-run" in argv
    global DELAY
    DELAY = float(arg("--delay", DELAY))
    seed_path = Path(arg("--seed", ROOT / "fixtures" / "seed_data.json"))
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    invoices = [dict(i, kind="out_invoice", doc_id=i["invoice_id"], partner=i["customer_id"], date=i["invoice_date"])
                for i in data["invoices"][:limit]]
    bills = [dict(b, kind="in_invoice", doc_id=b["bill_id"], partner=b["supplier_id"], date=b["bill_date"], dispute=False)
             for b in data.get("bills", [])[:limit]]
    invoices = invoices + bills          # hóa đơn bán và hóa đơn mua đi chung một quy trình
    if "--only-bills" in argv:            # đã nạp hóa đơn bán rồi, chỉ nạp thêm phía phải trả
        invoices = [i for i in invoices if i["kind"] == "in_invoice"]
    since = arg("--since")               # chỉ nạp chứng từ từ ngày này; chứng từ còn nợ thì luôn giữ
    if since:
        invoices = [i for i in invoices if i["date"] >= since or sum(p["amount"] for p in i["payments"]) < i["amount"]]
    extra_partners = []
    if "--obligations" in argv:           # khoản chi cố định (lương, thuế, bảo hiểm...) nạp thành hóa đơn nhà cung cấp
        obl = json.loads((seed_path.parent / "obligations.json").read_text(encoding="utf-8"))
        names = sorted({o["counterparty"] for o in obl})
        pid_of = {n: f"S9{k:02d}" for k, n in enumerate(names, 1)}
        extra_partners = [{"pid": pid_of[n], "name": n, "email": f"thanhtoan.s9{k:02d}@ncc-demo.example.test"}
                          for k, n in enumerate(names, 1)]
        for k, o in enumerate(obl, 1):
            invoices.append({"kind": "in_invoice", "doc_id": f"BILL-OBL-{k:03d}", "partner": pid_of[o["counterparty"]],
                             "date": data.get("as_of", "2026-11-09"), "due_date": o["due_date"], "amount": o["amount"],
                             "dispute": False, "payments": [],
                             "narration": f"{o['description']} [{o['kind']}, ưu tiên {o['priority']}, hoãn tối đa {o['can_defer_days']} ngày]",
                             "lines": [{"sku": None, "name": o["description"], "qty": 1, "unit_price": o["amount"]}]})
    bills = [i for i in invoices if i["kind"] == "in_invoice"]
    used = {i["partner"] for i in invoices}
    customers = [dict(c, pid=c["customer_id"]) for c in data["customers"] if c["customer_id"] in used]
    customers += extra_partners
    customers += [dict(x, pid=x["supplier_id"]) for x in data.get("suppliers", []) if x["supplier_id"] in used]
    print(f"Kế hoạch: {len(customers) - len(bills and set(b['partner'] for b in bills))} khách, "
          f"{len(set(b['partner'] for b in bills))} nhà cung cấp, {len(invoices) - len(bills)} hóa đơn bán, "
          f"{len(bills)} hóa đơn mua từ {seed_path.name}")
    if dry:
        n_full = sum(1 for i in invoices if len(i["payments"]) == 1)
        print(f"  trả đủ một lần: {n_full} hóa đơn, trả góp: {sum(1 for i in invoices if len(i['payments']) > 1)}, "
              f"chưa trả: {sum(1 for i in invoices if not i['payments'])}")
        return
    load_env()
    connect()
    t0 = time.time()

    # 1. Khách hàng theo lô
    existing_p = {r["ref"]: r["id"] for r in call("res.partner", "search_read", [["ref", "in", [c["pid"] for c in customers]]], fields=["ref"])}
    new_c = [c for c in customers if c["pid"] not in existing_p]
    for part in chunks(new_c, batch):
        ids = as_ids(call("res.partner", "create", [{"name": c["name"], "ref": c["pid"], "email": c["email"]} for c in part]), len(part))
        existing_p.update({c["pid"]: i for c, i in zip(part, ids)})
    print(f"Đối tác (khách và nhà cung cấp): tạo mới {len(new_c)}, đã có {len(customers) - len(new_c)}")

    # 1b. Sản phẩm theo lô (nếu seed_data có danh mục hàng)
    product_id = {}
    products = data.get("products", [])
    used_skus = {l["sku"] for i in invoices for l in i.get("lines", []) if l.get("sku")}
    products = [p for p in products if p["sku"] in used_skus]
    if products:
        product_id = {r["default_code"]: r["id"] for r in call(
            "product.product", "search_read", [["default_code", "in", [p["sku"] for p in products]]], fields=["default_code"])}
        new_p = [p for p in products if p["sku"] not in product_id]
        for part in chunks(new_p, batch):
            ids = as_ids(call("product.product", "create", [
                {"name": p["name"], "default_code": p["sku"], "list_price": p["unit_price"], "type": "consu"} for p in part]), len(part))
            product_id.update({p["sku"]: i for p, i in zip(part, ids)})
        print(f"Sản phẩm: tạo mới {len(new_p)}, đã có {len(products) - len(new_p)}")

    # 2. Hóa đơn đã có trong Odoo (để chạy lại được)
    existing = {}
    refs = [i["doc_id"] for i in invoices]
    for part in chunks(refs, 400):
        for r in call("account.move", "search_read", [["ref", "in", part], ["move_type", "in", ["out_invoice", "in_invoice"]]],
                      fields=["ref", "state", "amount_total", "amount_residual"]):
            existing[r["ref"]] = r

    # 3. Tạo hóa đơn theo lô
    move_id = {ref: r["id"] for ref, r in existing.items()}
    to_create = [i for i in invoices if i["doc_id"] not in existing]
    for part in chunks(to_create, batch):
        def lines_of(i):
            if i.get("lines"):
                out = []
                for l in i["lines"]:
                    v = {"name": l["name"], "quantity": l["qty"], "price_unit": l["unit_price"], "tax_ids": [[6, 0, []]]}
                    if l.get("sku") and l["sku"] in product_id:
                        v["product_id"] = product_id[l["sku"]]      # dòng dịch vụ (cước vận chuyển) không có mã hàng
                    out.append([0, 0, v])
                return out
            return [[0, 0, {"name": "Demo " + i["doc_id"], "quantity": 1, "price_unit": i["amount"],
                            "tax_ids": [[6, 0, []]]}]]      # không thuế, để tổng tiền đúng bằng amount

        vals = [{
            "move_type": i["kind"], "partner_id": existing_p[i["partner"]], "ref": i["doc_id"],
            "invoice_date": i["date"], "invoice_date_due": i["due_date"],
            "narration": i.get("narration") or ("[DISPUTE]" if i["dispute"] else False),
            "invoice_line_ids": lines_of(i),
        } for i in part]
        ids = as_ids(call("account.move", "create", vals), len(part))
        move_id.update({i["doc_id"]: mid for i, mid in zip(part, ids)})
        call("account.move", "action_post", ids)
        print(f"  đã tạo và xác nhận {len(ids)} chứng từ ({time.time() - t0:.0f}s)")
    drafts = [r["id"] for r in existing.values() if r["state"] == "draft"]
    if drafts:
        call("account.move", "action_post", drafts)
    print(f"Hóa đơn (bán và mua): tạo mới {len(to_create)}, đã có {len(existing)}")

    # 4. Thanh toán
    by_date, single = defaultdict(list), []
    for inv in invoices:
        pend = pending_payments(inv, existing.get(inv["doc_id"]))
        for p in pend:
            if len(inv["payments"]) == 1 and inv["payments"][0]["amount"] == inv["amount"]:   # trả đủ một lần
                by_date[(p["date"], inv["kind"])].append(move_id[inv["doc_id"]])   # không gộp hóa đơn bán và mua chung một lần
            else:
                single.append((move_id[inv["doc_id"]], p))

    def pay_one(mid, date, amount=None):
        ctx = {"active_model": "account.move", "active_ids": [mid]}
        vals = {"payment_date": date}
        if amount is not None:
            vals["amount"] = amount
        w = call("account.payment.register", "create", vals, context=ctx)
        call("account.payment.register", "action_create_payments", [w], context=ctx)

    done = failed = 0
    for n, ((date, _kind), mids) in enumerate(sorted(by_date.items()), 1):
        ctx = {"active_model": "account.move", "active_ids": mids}
        try:
            w = call("account.payment.register", "create", {"payment_date": date, "group_payment": False}, context=ctx)
            call("account.payment.register", "action_create_payments", [w], context=ctx)
            done += len(mids)
        except Exception as e:                       # nhóm lỗi thì làm riêng từng hóa đơn
            print(f"  nhóm ngày {date} lỗi ({str(e)[:80]}), chuyển sang làm riêng")
            for mid in mids:
                try:
                    pay_one(mid, date)
                    done += 1
                except Exception as e2:
                    failed += 1
                    print(f"  LỖI thanh toán hóa đơn id {mid}: {str(e2)[:100]}")
        if n % 50 == 0:
            print(f"  đã xử lý {n}/{len(by_date)} ngày thanh toán ({time.time() - t0:.0f}s)")
    for mid, p in single:
        try:
            pay_one(mid, p["date"], p["amount"])
            done += 1
        except Exception as e:
            failed += 1
            print(f"  LỖI trả góp hóa đơn id {mid}: {str(e)[:100]}")
    print(f"Thanh toán: tạo {done}, lỗi {failed}")
    print(f"Hoàn tất sau {time.time() - t0:.0f} giây.")


if __name__ == "__main__":
    main()
