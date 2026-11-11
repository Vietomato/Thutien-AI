"""Xóa hóa đơn khách hàng (out_invoice) và thanh toán liên quan trong Odoo.

Mặc định chỉ đếm (dry-run). Thêm --yes để xóa thật. Thêm --bills để xóa cả hóa đơn nhà cung cấp.
"""
import os
import sys
import xmlrpc.client
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for env_file in (root / ".env", root / "backend" / ".env"):
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

URL = (os.getenv("ODOO_URL") or "").rstrip("/")
if URL.endswith("/odoo"):
    URL = URL[:-5]
DB = os.getenv("ODOO_DB") or os.getenv("ODOO_DB_NAME", "odoo")
USER = os.getenv("ODOO_EMAIL") or os.getenv("ODOO_SETUP_USER", "")
PWD = os.getenv("ODOO_API_KEY") or os.getenv("ODOO_SETUP_PASSWORD", "")
YES = "--yes" in sys.argv
BILLS = "--bills" in sys.argv

uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True).authenticate(DB, USER, PWD, {})
if not uid:
    sys.exit("Đăng nhập thất bại: kiểm tra .env")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)


def call(model, method, *args, **kwargs):
    try:
        return models.execute_kw(DB, uid, PWD, model, method, list(args), kwargs)
    except xmlrpc.client.Fault as e:
        # Hàm trả None: Odoo đã chạy xong nhưng không đóng gói được kết quả. Bỏ qua.
        if "cannot marshal None" in str(e):
            return None
        raise


types = ["out_invoice", "out_refund"] + (["in_invoice", "in_refund"] if BILLS else [])
move_ids = call("account.move", "search", [["move_type", "in", types]])
pay_ids = call("account.payment", "search", [])
print(f"DB: {DB} @ {URL}")
print(f"Hóa đơn sẽ xóa ({', '.join(types)}): {len(move_ids)}")
print(f"Thanh toán sẽ xóa: {len(pay_ids)}")

if not YES:
    print("\nDry-run: chưa xóa gì. Chạy lại với --yes để xóa thật.")
    sys.exit(0)

# 1. Hủy/xóa thanh toán trước (gỡ đối soát)
pdone = 0
for p in call("account.payment", "read", pay_ids, fields=["state"]):
    pid = p["id"]
    try:
        if p["state"] != "draft":
            call("account.payment", "action_draft", [pid])
        call("account.payment", "unlink", [pid])
        pdone += 1
    except Exception as e:
        print(f"Không xóa được payment {pid} (state={p['state']}): {str(e)[:150]}")
print(f"Đã xóa {pdone}/{len(pay_ids)} thanh toán.")

# 2. Đưa hóa đơn về draft rồi xóa
done = 0
for m in call("account.move", "read", move_ids, fields=["state"]):
    mid = m["id"]
    try:
        if m["state"] != "draft":
            call("account.move", "button_draft", [mid])
        call("account.move", "unlink", [mid])
        done += 1
    except Exception as e:
        print(f"Không xóa được move {mid}: {str(e)[:150]}")
print(f"Hoàn tất: đã xóa {done}/{len(move_ids)} hóa đơn.")
print("Còn lại - hóa đơn:", len(call("account.move", "search", [["move_type", "in", types]])),
      "| thanh toán:", len(call("account.payment", "search", [])))
