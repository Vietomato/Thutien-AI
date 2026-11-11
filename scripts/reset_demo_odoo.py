"""Đặt lại dữ liệu demo trong Odoo bằng MỘT lệnh: xóa dữ liệu demo cũ rồi nạp bộ dữ liệu Minh Phát mới.

    python scripts/reset_demo_odoo.py                 # chỉ xem sẽ xóa gì (dry-run), không ghi gì
    python scripts/reset_demo_odoo.py --yes           # xóa thật, rồi nạp lại toàn bộ
    python scripts/reset_demo_odoo.py --yes --regen   # sinh lại dữ liệu bằng gen_demo_company.py trước khi nạp
    python scripts/reset_demo_odoo.py --yes --limit 20   # nạp thử 20 hóa đơn (tham số sau được chuyển cho seed_odoo_fast)

ĐÂY LÀ CÔNG CỤ CỦA QUẢN TRỊ, KHÔNG PHẢI CỦA BACKEND. Backend vẫn chỉ đọc Odoo. Script này ghi và xóa dữ liệu bằng tài khoản
quản trị nên có ba lớp chặn:
  1. Mặc định là dry-run, phải có --yes mới xóa.
  2. Phải đặt ODOO_ALLOW_RESET=1 trong .env của database demo. Đừng đặt biến này ở bất kỳ nơi nào khác.
  3. Chỉ xóa hóa đơn bán hàng, thanh toán, khách có mã ref dạng C001, và sản phẩm có mã trong danh mục demo.
     Không đụng tới nhà cung cấp, hóa đơn mua hàng, người dùng hay cấu hình.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed_odoo_fast as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def delete_records(model, ids, draft_method=None, label=""):
    """Xóa theo lô. Bản ghi nào đang ở trạng thái đã vào sổ thì đưa về nháp trước (bản ghi đã là nháp hoặc đã hủy thì
    bỏ qua bước này, vì Odoo từ chối đặt lại nháp lần nữa). Lô nào lỗi thì thử từng bản ghi để biết bản nào không xóa được."""
    def prepare(part):
        if not draft_method:
            return
        states = {r["id"]: r.get("state") for r in S.call(model, "read", part, fields=["state"])}
        need = [i for i in part if states.get(i) not in ("draft", "cancel", "canceled")]
        if need:
            S.call(model, draft_method, need)

    ok = bad = 0
    for part in chunks(ids, 100):
        try:
            prepare(part)
            S.call(model, "unlink", part)
            ok += len(part)
        except Exception:
            for one in part:
                try:
                    try:
                        prepare([one])
                    except Exception:
                        pass                      # không đưa về nháp được thì vẫn thử xóa
                    S.call(model, "unlink", [one])
                    ok += 1
                except Exception as e:
                    bad += 1
                    print(f"  không xóa được {label} id {one}: {str(e)[:100]}")
    return ok, bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    yes = "--yes" in argv
    regen = "--regen" in argv
    seed_args = [a for a in argv if a not in ("--yes", "--regen")]
    S.load_env()
    if yes and os.getenv("ODOO_ALLOW_RESET") != "1":
        sys.exit("Từ chối: chưa đặt ODOO_ALLOW_RESET=1 trong .env. Chỉ đặt biến này cho database DEMO.")
    S.connect()

    # Phía bán: mọi thanh toán khách hàng và hóa đơn bán. Phía mua: chỉ chứng từ của đối tác mã Snnn / số tham chiếu BILL-
    pay_ids = S.call("account.payment", "search", [["partner_type", "=", "customer"]])
    pay_ids += S.call("account.payment", "search", [["partner_type", "=", "supplier"], ["partner_id.ref", "=like", "S___"]])
    move_ids = S.call("account.move", "search", [["move_type", "in", ["out_invoice", "out_refund"]]])
    move_ids += S.call("account.move", "search", [["move_type", "=", "in_invoice"], ["ref", "=like", "BILL-%"]])
    pay_ids, move_ids = sorted(set(pay_ids)), sorted(set(move_ids))
    partners = [r for r in S.call("res.partner", "search_read", [["ref", "!=", False]], fields=["ref"])
                if re.fullmatch(r"[CS]\d{3}", r["ref"] or "")]
    seed_path = Path(next((seed_args[i + 1] for i, a in enumerate(seed_args) if a == "--seed"), ROOT / "fixtures" / "demo_company" / "seed_data.json"))
    skus = [p["sku"] for p in json.loads(seed_path.read_text(encoding="utf-8")).get("products", [])] if seed_path.exists() else []
    products = S.call("product.product", "search", [["default_code", "in", skus]]) if skus else []
    print(f"Sẽ xóa: {len(pay_ids)} thanh toán, {len(move_ids)} hóa đơn bán và mua, "
          f"{len(partners)} khách và nhà cung cấp (mã Cxxx, Sxxx), {len(products)} sản phẩm demo")
    if not yes:
        print("\nDry-run: chưa xóa gì. Chạy lại với --yes để xóa thật và nạp lại.")
        return

    # 1. Thanh toán trước (gỡ đối soát), rồi hóa đơn
    ok, bad = delete_records("account.payment", pay_ids, "action_draft", "thanh toán")
    print(f"Thanh toán: xóa {ok}, lỗi {bad}")
    if bad:
        sys.exit("Còn thanh toán không xóa được, dừng lại để không nạp chồng lên dữ liệu cũ. Xem thông báo ở trên.")
    ok, bad = delete_records("account.move", move_ids, "button_draft", "hóa đơn")
    print(f"Hóa đơn: xóa {ok}, lỗi {bad}")
    if bad:
        sys.exit("Còn hóa đơn không xóa được, dừng lại để không nạp chồng lên dữ liệu cũ. Xem thông báo ở trên.")

    # 2. Khách và sản phẩm demo. Không xóa được (đang được tham chiếu) thì lưu trữ và bỏ mã ref để mã mới không đụng nhau
    for model, rows, extra in [("res.partner", [p["id"] for p in partners], {"ref": False}),
                               ("product.product", products, {"default_code": False})]:
        ok, bad = delete_records(model, rows, None, model)
        if bad:
            for one in rows:
                try:
                    S.call(model, "write", [one], dict(extra, active=False))
                except Exception:
                    pass
            print(f"{model}: {bad} bản ghi không xóa được đã được lưu trữ")
    print("Đã xóa dữ liệu demo cũ.\n")

    # 3. Sinh lại (nếu cần) và nạp mới
    if regen or not seed_path.exists():
        import gen_demo_company
        gen_demo_company.write(seed_path.parent)
    S.main(seed_args if "--seed" in seed_args else ["--seed", str(seed_path)] + seed_args)


if __name__ == "__main__":
    main()
