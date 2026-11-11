"""Sinh dữ liệu demo cho công ty giả lập "Minh Phát" (phân phối vật liệu xây dựng và thiết bị điện nước).

Toàn bộ tên công ty, dự án, email, số tiền đều là GIẢ LẬP (email dùng đuôi .example.test). Mọi sự trùng tên với doanh
nghiệp thật là ngẫu nhiên. Hóa đơn gồm nhiều dòng hàng (số lượng x đơn giá nên tổng tiền lẻ như thật), khách chia thành
nhà thầu / doanh nghiệp / cửa hàng với thói quen mua và trả khác nhau, có mùa vụ (Tết, cuối năm), ngày nghỉ lễ,
nhà thầu trả theo đợt. Thói quen trả tiền được hiệu chỉnh theo thống kê của bộ Kaggle Payment Date
(không sao chép dòng nào từ bộ đó).

Phía PHẢI TRẢ: 13 nhà cung cấp với hóa đơn mua hàng (giá vốn khoảng 78% giá bán, mua trước khi bán), công ty trả đúng hạn
hoặc trễ vài ngày; các khoản chi cố định hằng tháng (lương, bảo hiểm, thuế, thuê kho, vay ngân hàng) kèm mức ưu tiên và khả năng
hoãn; số dư tiền đầu kỳ. Đủ để vẽ chuỗi "khách trả chậm -> thiếu tiền tuần nào -> khoản phải chi nào bị ảnh hưởng".

Chạy:   python scripts/gen_demo_company.py            -> ghi vào fixtures/demo_company/
        python scripts/gen_demo_company.py <thư mục>  -> ghi vào thư mục khác
Kết quả cố định (seed cố định): ai chạy cũng ra đúng cùng một dữ liệu.
"""
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

AS_OF = date(2026, 11, 9)     # trùng AS_OF_DATE của backend
START = date(2025, 5, 2)      # khoảng 18 tháng lịch sử
DRIFT_FROM = date(2026, 7, 15)
M = 1_000_000
rng = np.random.default_rng(20261109)

# Ngày nghỉ lễ (xấp xỉ, đủ để tạo hiệu ứng thật): Quốc khánh, Tết Dương lịch, Tết Nguyên đán 2026, Giỗ Tổ, 30/4 - 1/5
HOLIDAYS = {date(2025, 9, 1), date(2025, 9, 2), date(2026, 1, 1), date(2026, 4, 27), date(2026, 4, 30),
            date(2026, 5, 1), date(2026, 9, 2)}
HOLIDAYS |= {date(2026, 2, 14) + timedelta(days=k) for k in range(9)}          # 14 đến 22/2/2026
SEASON = {1: .8, 2: .5, 3: .95, 4: 1.05, 5: 1.1, 6: 1.05, 7: 1.0, 8: 1.0, 9: 1.05, 10: 1.15, 11: 1.2, 12: 1.1}

# Danh mục hàng: (mã, tên, đơn vị, đơn giá VND, nhóm, số lượng điển hình cho một khách cỡ trung bình)
PRODUCTS = [
    ("XM-PCB40", "Xi măng PCB40 (bao 50kg)", "bao", 93_000, "khung", 180),
    ("TH-CUON8", "Thép cuộn phi 8", "kg", 17_400, "khung", 2_500),
    ("TH-D16", "Thép thanh vằn D16", "kg", 17_900, "khung", 3_000),
    ("GACH-O4", "Gạch ống 4 lỗ", "viên", 1_350, "khung", 4_000),
    ("CAT-VANG", "Cát vàng xây tô", "m3", 320_000, "khung", 20),
    ("DA-1X2", "Đá 1x2", "m3", 385_000, "khung", 20),
    ("TGC-9", "Tấm thạch cao 9mm", "tấm", 98_000, "hoanthien", 120),
    ("SON-NT18", "Sơn nội thất 18L", "thùng", 1_850_000, "hoanthien", 16),
    ("SON-NGT18", "Sơn ngoại thất 18L", "thùng", 2_950_000, "hoanthien", 10),
    ("GACH-60", "Gạch lát 60x60", "m2", 215_000, "hoanthien", 150),
    ("KEO-GACH", "Keo dán gạch 25kg", "bao", 125_000, "hoanthien", 60),
    ("PPR-25", "Ống nhựa PPR phi 25", "m", 38_000, "nuoc", 150),
    ("PVC-90", "Ống PVC phi 90", "m", 62_000, "nuoc", 100),
    ("VAN-21", "Van khóa nước phi 21", "cái", 85_000, "nuoc", 40),
    ("BON-INOX", "Bồn nước inox 1000L", "cái", 3_350_000, "nuoc", 4),
    ("BO-VS", "Bộ thiết bị vệ sinh bồn cầu + lavabo", "bộ", 2_650_000, "nuoc", 8),
    ("CAP-2X25", "Dây cáp điện 2x2.5 (cuộn 100m)", "cuộn", 1_180_000, "dien", 12),
    ("APTOMAT-40", "Aptomat 2P 40A", "cái", 165_000, "dien", 40),
    ("TU-DIEN", "Tủ điện âm tường 12 module", "cái", 420_000, "dien", 15),
    ("DEN-LED", "Đèn LED panel 600x600", "cái", 380_000, "dien", 50),
    ("O-CAM", "Bộ ổ cắm công tắc", "bộ", 65_000, "dien", 120),
    ("CUA-NHOM", "Cửa nhôm kính", "m2", 1_650_000, "kinh", 14),
    ("KINH-10", "Kính cường lực 10mm", "m2", 980_000, "kinh", 20),
    ("MU-BH", "Mũ bảo hộ lao động", "cái", 55_000, "bhld", 100),
    ("GANG-TAY", "Găng tay bảo hộ", "đôi", 12_000, "bhld", 300),
]
SKU = {p[0]: p for p in PRODUCTS}
BY_CAT = {}
for p in PRODUCTS:
    BY_CAT.setdefault(p[4], []).append(p[0])
CAT_WEIGHTS = {   # nhóm hàng mà từng loại khách hay mua
    "contractor": {"khung": 40, "hoanthien": 20, "nuoc": 15, "dien": 10, "kinh": 10, "bhld": 5},
    "enterprise": {"dien": 35, "nuoc": 20, "kinh": 15, "hoanthien": 20, "bhld": 10},
    "shop": {"nuoc": 30, "dien": 30, "hoanthien": 25, "bhld": 15},
}
SEG = {  # kích cỡ, điều khoản, chu kỳ đặt hàng, dịch độ trễ so với kiểu khách
    "contractor": dict(size=1.0, terms=([30, 45, 60], [.4, .4, .2]), interval=14, shift=0.5),
    "enterprise": dict(size=0.45, terms=([30, 45], [.6, .4]), interval=30, shift=0.0),
    "shop": dict(size=0.12, terms=([0, 7, 15, 30], [.25, .25, .3, .2]), interval=16, shift=-1.0),
}
PROJECTS = ["Nhà xưởng cơ khí Khu CN Bắc Hà", "Chung cư mini Hoa Sữa", "Trường mầm non Sao Mai", "Khu nhà ở Phú An (giai đoạn 2)",
            "Showroom ô tô Đại Việt", "Kho lạnh An Dương", "Văn phòng cho thuê Tân Cảng", "Nhà phố liền kề Thanh Hà",
            "Cải tạo bệnh xá Bình An", "Khách sạn mini Biển Xanh", "Nhà máy may Hòa Lộc", "Căn hộ dịch vụ Mai Linh"]

# Nhà cung cấp: (tên, nhóm mã hàng, điều khoản trả (ngày), chiến lược: ngừng giao hàng khi chậm trả, phạt chậm trả %/tháng - GIẢ ĐỊNH demo)
SUPPLIERS = [
    ("Công ty CP Thép Đại Nam", ["TH-CUON8", "TH-D16"], 30, True, 1.5),
    ("Công ty TNHH Xi măng Thiên Phú", ["XM-PCB40"], 15, True, 1.5),
    ("Công ty TNHH Vật liệu Xây dựng Phú Gia", ["GACH-O4", "CAT-VANG", "DA-1X2"], 7, False, 1.0),
    ("Công ty TNHH Sơn Tân Lộc", ["SON-NT18", "SON-NGT18"], 30, False, 1.0),
    ("Công ty CP Gạch ốp lát Đại Việt", ["GACH-60", "KEO-GACH"], 30, False, 1.0),
    ("Công ty TNHH Thạch cao Hồng Phát", ["TGC-9"], 30, False, 1.0),
    ("Công ty CP Nhựa ống Phương Đông", ["PPR-25", "PVC-90", "VAN-21"], 30, False, 1.0),
    ("Công ty TNHH Thiết bị vệ sinh Hoàng Long", ["BON-INOX", "BO-VS"], 45, False, 1.0),
    ("Công ty CP Dây cáp điện Việt Cường", ["CAP-2X25"], 30, True, 1.5),
    ("Công ty TNHH Thiết bị điện Minh Quang", ["APTOMAT-40", "TU-DIEN", "DEN-LED", "O-CAM"], 45, False, 1.0),
    ("Công ty TNHH Nhôm kính Tân Hưng", ["CUA-NHOM", "KINH-10"], 30, False, 1.0),
    ("Công ty TNHH Bảo hộ lao động An Toàn", ["MU-BH", "GANG-TAY"], 15, False, 1.0),
    ("Công ty TNHH Vận tải Hà Phát", [], 15, False, 0.5),                      # cước vận chuyển (dịch vụ, không có mã hàng)
]
COST_RATIO = 0.78      # giá vốn so với giá bán: biên lợi nhuận gộp khoảng 22%

# (tên, kiểu thói quen trả tiền)
CUSTOMERS = (
    [(n, "early") for n in [
        "Công ty TNHH Xây dựng Phú Cường", "Công ty CP Vật tư Nam Việt", "Công ty TNHH Thiết bị Sao Mai",
        "Công ty TNHH Cơ điện Hải Đăng", "Công ty CP Bất động sản Thịnh Vượng", "Công ty TNHH Nội thất Gia Huy",
        "Cửa hàng VLXD Hoàng Gia"]]
    + [(n, "normal") for n in [
        "Công ty TNHH Vận tải Trường An", "Cửa hàng Điện nước Hoa Mai", "Công ty CP Xây dựng Số 9",
        "Công ty TNHH Thiết kế Kiến Việt", "Công ty TNHH Sản xuất Nhôm Kính Á Châu",
        "Công ty CP Cấp thoát nước Sông Hồng", "Công ty TNHH Xây dựng Tân Long",
        "Công ty TNHH Dịch vụ Kỹ thuật Minh Anh", "Cửa hàng Sắt thép Tuấn Hùng",
        "Công ty TNHH Trang trí Nội thất Lộc Phát", "Công ty CP Xây dựng Thăng Long",
        "Công ty TNHH Điện lạnh Tân Phát", "Công ty CP Kỹ thuật Việt Tiến", "Công ty TNHH Xây lắp Đại Dương",
        "Công ty TNHH Thương mại Kim Long", "Công ty CP Đầu tư Xây dựng Bắc Hà",
        "Công ty TNHH MTV Cơ khí Long Biên", "Công ty TNHH Xây dựng Phương Nam", "Công ty CP Kiến trúc Tân Á",
        "Công ty TNHH Sơn Thiên Phúc"]]
    + [(n, "late") for n in [
        "Công ty TNHH Xây dựng Hưng Thịnh", "Công ty CP Thương mại Đông Dương", "Công ty TNHH Cơ khí Quang Minh"]]
    + [(n, "chronic") for n in ["Công ty CP Tổng thầu Đại Phát", "Công ty TNHH Xây dựng Bình Minh"]]
    + [(n, "erratic") for n in ["Công ty TNHH Xây dựng Tiến Đạt", "Công ty CP Công trình Giao thông 7"]]
)
_EXTRA = (
    [(n, "early") for n in [
        "Công ty TNHH Xây dựng Hải Long", "Công ty CP Thiết bị Công nghiệp An Bình", "Cửa hàng VLXD Minh Khôi",
        "Công ty TNHH Cơ điện Lạnh Thái Sơn"]]
    + [(n, "normal") for n in [
        "Công ty TNHH Xây dựng Đông Hưng", "Cửa hàng Điện nước Thanh Bình", "Công ty CP Vận tải Xây dựng Hải Vân",
        "Công ty TNHH Nhôm Kính Việt Mỹ", "Công ty CP Cơ khí Xây lắp Sông Lam", "Công ty TNHH Thiết bị PCCC Bảo An",
        "Công ty TNHH Sắt thép Hòa Mai", "Cửa hàng Vật tư Ngọc Sơn", "Công ty TNHH Xây dựng Dân dụng Phúc Lộc",
        "Công ty TNHH Tư vấn Thiết kế Hà Thành", "Công ty CP Nội thất Văn phòng Á Đông",
        "Công ty TNHH Điện máy Quang Huy", "Công ty TNHH Ống nhựa Hưng Phát", "Công ty TNHH Thang máy Việt Thành"]]
    + [(n, "late") for n in ["Công ty TNHH Xây dựng Trường Thịnh", "Công ty CP Công trình Đô thị Tây Nam"]]
    + [("Công ty TNHH Thi công Công trình Việt Hùng", "chronic")]
    + [(n, "erratic") for n in ["Công ty CP Xây dựng Hạ tầng Đông Anh", "Công ty TNHH Xây dựng Sao Việt"]]
)
CUSTOMERS = CUSTOMERS + _EXTRA + [
    ("Công ty CP Xây dựng Nhật Quang", "drift"),      # đang chuyển từ đúng hẹn sang trễ
    ("Cửa hàng VLXD Thành Đạt", "normal"),             # có hóa đơn tranh chấp
    ("Công ty TNHH Nội thất An Khang", "new"),         # khách mới, chưa có lịch sử
]
BIG_LATE = "Công ty CP Tổng thầu Đại Phát"
DISPUTE = "Cửa hàng VLXD Thành Đạt"
NEW = "Công ty TNHH Nội thất An Khang"


def is_off(d):
    return d.weekday() >= 5 or d in HOLIDAYS


def next_workday(d):
    while is_off(d):
        d += timedelta(days=1)
    return d


def prev_workday(d):
    while is_off(d):
        d -= timedelta(days=1)
    return d


def land_on_workday(d):
    """Khoản trả rơi vào ngày nghỉ thì dời về ngày làm việc trước (đi trước kỳ nghỉ) hoặc sau, 50/50."""
    if is_off(d):
        return prev_workday(d) if rng.random() < 0.5 else next_workday(d)
    return d


def segment(name):
    if name.startswith("Cửa hàng"):
        return "shop"
    if any(k in name for k in ["Xây dựng", "Xây lắp", "Tổng thầu", "Thi công", "Công trình"]):
        return "contractor"
    return "enterprise"


def make_customer(i, name, kind):
    u = rng.uniform
    mu, sigma, outlier = {
        "early": (u(-5, -2), u(1.5, 3), 0.0),
        "normal": (u(-2.0, 2.5), u(2, 5), 0.0),
        "late": (u(3, 7), u(4, 7), 0.0),
        "chronic": (u(12, 26), u(5, 10), 0.0),
        "erratic": (u(-1, 1), 3.0, 0.2),
        "drift": (-1.0, 2.0, 0.0),
        "new": (0.0, 3.0, 0.0),
    }[kind]
    seg = segment(name)
    sp = SEG[seg]
    weights = CAT_WEIGHTS[seg]
    pool = [s for cat, w in weights.items() for s in BY_CAT[cat] for _ in range(w)]
    favs = []
    while len(favs) < 5:
        s = pool[int(rng.integers(len(pool)))]
        if s not in favs:
            favs.append(s)
    pay_dow = int(rng.choice([3, 4])) if seg == "enterprise" and rng.random() < 0.4 else None
    if pay_dow is not None:
        mu -= 2.5          # chờ ngày chi cố định trong tuần đã cộng thêm khoảng 3 ngày, trừ lại để tổng thể không lệch
    mu -= 1.0
    terms = int(rng.choice(sp["terms"][0], p=sp["terms"][1])) if kind != "chronic" else 30
    return dict(
        customer_id=f"C{i:03d}", name=name, kind=kind, seg=seg, mu=mu + sp["shift"], sigma=sigma, outlier=outlier,
        email=f"ketoan.c{i:03d}@khach-demo.example.test", terms=terms,
        size=sp["size"] * float(np.clip(rng.lognormal(0, 0.6), 0.35, 3.5)),
        interval=float(np.clip(rng.lognormal(np.log(sp["interval"]), 0.4), 5, 70)),
        discount=float(rng.uniform(0.94, 1.0)), favs=favs,
        pay_dow=pay_dow,
        projects=[PROJECTS[int(k)] for k in rng.choice(len(PROJECTS), 3, replace=False)] if seg == "contractor" else [],
    )


def unit_price(sku, c, when):
    months = (when.year - START.year) * 12 + when.month - START.month
    return int(round(SKU[sku][3] * c["discount"] * (1 + 0.03 * months / 18) / 100) * 100)   # lạm phát nhẹ, làm tròn 100đ


def make_lines(c, when, target=None, skus=None):
    pool = skus or c["favs"]
    k = int(rng.choice([1, 2, 3, 4], p=[.3, .4, .22, .08])) if not skus else len(skus)
    picked = [str(x) for x in rng.choice(pool, size=min(k, len(pool)), replace=False)] if not skus else list(skus)
    raw = []
    for s in picked:
        q = SKU[s][5] * c["size"] * float(rng.lognormal(0, 0.45))
        raw.append([s, q])
    if target:
        f = target / sum(q * unit_price(s, c, when) for s, q in raw)
        for r in raw:
            r[1] *= f
    return [dict(sku=s, name=SKU[s][1], unit=SKU[s][2], qty=max(1, int(round(q))), unit_price=unit_price(s, c, when))
            for s, q in raw]


def sample_delay(c, invoice_date, due, amount):
    mu, sigma = c["mu"], c["sigma"]
    if c["kind"] == "drift" and invoice_date >= DRIFT_FROM:
        mu, sigma = 22.0, 6.0
    z = rng.standard_t(5) / np.sqrt(5 / 3)       # đuôi dày hơn phân phối chuẩn, như Kaggle
    d = mu + sigma * z
    # Quy luật nhỏ có thật: hạn rơi cuối tháng dời sang đợt thanh toán sau, hóa đơn lớn hơn thường lệ duyệt chậm hơn,
    # điều khoản dài trả muộn hơn một chút.
    d += 2.0 * (due.day >= 28) + 1.5 * (amount > 1.4 * c["typ"]) + 1.0 * (c["terms"] >= 45)
    if c["outlier"] and rng.random() < c["outlier"]:
        d += rng.uniform(30, 70)
    return int(round(float(np.clip(d, -12, 120))))


def pay_date(due, delay, inv_date, c):
    d = due + timedelta(days=delay)
    if c["pay_dow"] is not None:                      # kế toán doanh nghiệp chạy lệnh chi vào một ngày cố định trong tuần
        d += timedelta(days=(c["pay_dow"] - d.weekday()) % 7)
    d = land_on_workday(d)
    return max(d, next_workday(inv_date))             # cửa hàng trả tiền mặt cùng ngày được, không trả trước ngày lập


def build():
    customers = [make_customer(i + 1, n, k) for i, (n, k) in enumerate(CUSTOMERS)]
    by_name = {c["name"]: c for c in customers}
    rows = []

    for c in customers:   # quy mô hóa đơn điển hình của khách: dùng cho luật "hóa đơn lớn hơn thường lệ thì trả chậm"
        c["typ"] = sum(SKU[s][5] * c["size"] * unit_price(s, c, START) for s in c["favs"]) / len(c["favs"]) * 1.9

    def add(c, inv_date, lines, terms, delay=None, dispute=False, unpaid=False, note=""):
        amount = sum(l["qty"] * l["unit_price"] for l in lines)
        due = inv_date + timedelta(days=terms)
        pays = []
        if not unpaid:
            delay = sample_delay(c, inv_date, due, amount) if delay is None else delay
            p_last = pay_date(due, delay, inv_date, c)
            # nhà thầu hay trả theo đợt nghiệm thu: hóa đơn lớn có thể chia 2 hoặc 3 đợt, đợt cuối rơi vào ngày p_last
            milestone = c["seg"] == "contractor" and amount >= 80 * M and rng.random() < 0.3
            partial = (not milestone) and amount >= 20 * M and rng.random() < 0.05
            if milestone or partial:
                shares = ([.5, .5] if partial or rng.random() < .5 else [.4, .3, .3])
                dates = [p_last]
                for _ in shares[1:]:
                    dates.insert(0, land_on_workday(dates[0] - timedelta(days=int(rng.integers(10, 35)))))
                dates = [max(d, next_workday(inv_date)) for d in dates]
                amts = [int(round(amount * s / 1000) * 1000) for s in shares[:-1]]
                amts.append(amount - sum(amts))
                pays = list(zip(dates, amts))
            else:
                pays = [(p_last, amount)]
            pays = [(d, a) for d, a in pays if d <= AS_OF]   # khoản trả sau ngày tính coi như chưa xảy ra
        rows.append(dict(customer=c, inv_date=inv_date, due=due, amount=amount, lines=lines, dispute=dispute,
                         pays=pays, note=note))

    seq = 0
    for c in customers:
        if c["kind"] == "new":
            continue
        d = START + timedelta(days=int(rng.integers(0, 25)))
        while d <= AS_OF:
            inv_date = next_workday(d)
            if inv_date > AS_OF:
                break
            if rng.random() < SEASON[inv_date.month] / 1.2:
                seq += 1
                note = (f"Công trình: {c['projects'][int(rng.integers(3))]}" if c["seg"] == "contractor"
                        else f"Đơn đặt hàng PO-{inv_date:%y%m}-{int(rng.integers(100, 999))}")
                add(c, inv_date, make_lines(c, inv_date), c["terms"], note=note)
            d += timedelta(days=max(1, int(round(c["interval"] * rng.uniform(0.5, 1.5)))))

    # Các tình huống cài sẵn cho buổi demo
    big = by_name[BIG_LATE]   # hóa đơn lớn của khách trễ thường xuyên: khoảng 60 tấn thép và 2.900 bao xi măng
    add(big, date(2026, 11, 3), [
        dict(sku="TH-D16", name=SKU["TH-D16"][1], unit="kg", qty=60_000, unit_price=unit_price("TH-D16", big, date(2026, 11, 3))),
        dict(sku="XM-PCB40", name=SKU["XM-PCB40"][1], unit="bao", qty=2_900, unit_price=unit_price("XM-PCB40", big, date(2026, 11, 3)))],
        15, unpaid=True, note="Công trình: Nhà xưởng cơ khí Khu CN Bắc Hà (đợt vật tư 3)")
    dsp = by_name[DISPUTE]    # quá hạn lâu, khách khiếu nại chất lượng sơn
    add(dsp, date(2026, 8, 5), make_lines(dsp, date(2026, 8, 5), target=185 * M, skus=["SON-NGT18", "SON-NT18", "KEO-GACH"]), 30,
        unpaid=True, dispute=True, note="Khách khiếu nại lô sơn ngoại thất, đang chờ đối chiếu")
    new = by_name[NEW]        # khách mới, chưa có lịch sử
    add(new, date(2026, 10, 20), make_lines(new, date(2026, 10, 20), target=64 * M, skus=["TGC-9", "DEN-LED", "O-CAM"]), 30,
        unpaid=True, note="Đơn đặt hàng đầu tiên")
    # Vài hóa đơn quá hạn chưa trả của khách hay trễ, để màn Nhắc nợ có việc để làm (quá hạn 11 đến 36 ngày)
    for name, inv_date, terms, target in [
            ("Công ty TNHH Xây dựng Bình Minh", date(2026, 9, 10), 30, 220), ("Công ty TNHH Xây dựng Hưng Thịnh", date(2026, 10, 2), 15, 88),
            ("Công ty CP Thương mại Đông Dương", date(2026, 9, 25), 30, 135), ("Công ty TNHH Xây dựng Tiến Đạt", date(2026, 8, 20), 45, 96),
            ("Công ty TNHH Cơ khí Quang Minh", date(2026, 10, 14), 15, 52)]:
        c = by_name[name]
        add(c, inv_date, make_lines(c, inv_date, target=target * M), terms, unpaid=True,
            note=f"Đơn đặt hàng PO-{inv_date:%y%m}-{int(rng.integers(100, 999))}")

    rows.sort(key=lambda r: (r["inv_date"], r["customer"]["customer_id"]))
    return customers, rows


def build_ap(rows):
    """Phía phải trả: hóa đơn mua hàng của nhà cung cấp. Mua hàng tỷ lệ với doanh số bán cùng nhóm mã hàng (giá vốn 78%),
    mua trước khi bán. Công ty trả nhà cung cấp gần đúng hạn, thỉnh thoảng kéo dài thêm vài ngày."""
    suppliers = [dict(supplier_id=f"S{i + 1:03d}", name=n, skus=sk, terms=t, strategic=st, late_fee=lf,
                      email=f"thanhtoan.s{i + 1:03d}@ncc-demo.example.test") for i, (n, sk, t, st, lf) in enumerate(SUPPLIERS)]
    by_id = {x["supplier_id"]: x for x in suppliers}
    sales, total = {}, {}
    for r in rows:
        key = (r["inv_date"].year, r["inv_date"].month)
        for l in r["lines"]:
            amt = l["qty"] * l["unit_price"]
            total[key] = total.get(key, 0) + amt
            for x in suppliers:
                if l["sku"] in x["skus"]:
                    sales[(x["supplier_id"], key)] = sales.get((x["supplier_id"], key), 0) + amt
    bills = []

    def cost_price(sku, when):
        months = (when.year - START.year) * 12 + when.month - START.month
        return int(round(SKU[sku][3] * COST_RATIO * float(rng.uniform(0.97, 1.03)) * (1 + 0.03 * months / 18) / 100) * 100)

    def add_bill(x, bill_date, lines, unpaid=False, note="", delay=None):
        amount = sum(l["qty"] * l["unit_price"] for l in lines)
        due = bill_date + timedelta(days=x["terms"])
        pays = []
        if not unpaid:
            d = int(round(float(rng.normal(0.5, 2)))) if delay is None else delay
            if delay is None and rng.random() < 0.12:
                d += int(rng.integers(5, 21))             # công ty kéo dài thanh toán khi tiền về chậm
            p = max(land_on_workday(due + timedelta(days=d)), next_workday(bill_date))
            if p <= AS_OF:
                pays = [(p, amount)]
        bills.append(dict(supplier=x, bill_date=bill_date, due=due, amount=amount, lines=lines, pays=pays, note=note))

    months = sorted(total)
    for key in months:
        y, m = key
        first = date(y, m, 1)
        days = (date(y + (m == 12), m % 12 + 1, 1) - first).days
        for x in suppliers:
            if x["skus"]:
                target = sales.get((x["supplier_id"], key), 0) * COST_RATIO * float(rng.uniform(0.9, 1.1))
            else:
                target = total[key] * 0.012 * float(rng.uniform(0.9, 1.1))           # cước vận chuyển
            if target < 5 * M:
                continue
            n = int(np.clip(round(target / (float(rng.uniform(80, 250)) * M)), 1, 5))
            shares = rng.dirichlet(np.ones(n)) * target
            for share in shares:
                d = first + timedelta(days=int(rng.integers(0, days)) - 5)         # mua trước khi bán khoảng 5 ngày
                bill_date = next_workday(min(max(d, date(2025, 4, 15)), AS_OF))
                if x["skus"]:
                    picked = [str(v) for v in rng.choice(x["skus"], size=min(len(x["skus"]), int(rng.integers(1, 3))), replace=False)]
                    parts = rng.dirichlet(np.ones(len(picked))) * share
                    lines = []
                    for sku, part in zip(picked, parts):
                        up = cost_price(sku, bill_date)
                        lines.append(dict(sku=sku, name=SKU[sku][1], qty=max(1, int(round(part / up))), unit_price=up))
                else:
                    lines = [dict(sku=None, name=f"Cước vận chuyển hàng hóa tháng {m}/{y}", qty=1,
                                  unit_price=int(round(share / 1000) * 1000))]
                add_bill(x, bill_date, lines)

    # Các khoản cài sẵn cho buổi demo
    steel, cement, brick, glass = (by_id[k] for k in ("S001", "S002", "S003", "S011"))
    big_row = next(r for r in rows if r["customer"]["name"] == BIG_LATE and r["inv_date"] == date(2026, 11, 3))
    add_bill(steel, date(2026, 10, 18), [
        dict(sku="TH-D16", name=SKU["TH-D16"][1], qty=45_000, unit_price=13_900),
        dict(sku="TH-CUON8", name=SKU["TH-CUON8"][1], qty=30_000, unit_price=13_500)],
        unpaid=True, note="Mua theo đơn hàng lớn của Tổng thầu Đại Phát")
    bills[-1]["link_row"] = big_row
    add_bill(cement, date(2026, 11, 5), [dict(sku="XM-PCB40", name=SKU["XM-PCB40"][1], qty=8_200, unit_price=72_500)],
             unpaid=True, note="Xi măng cho các công trình tháng 11")
    add_bill(brick, date(2026, 10, 12), [dict(sku="CAT-VANG", name=SKU["CAT-VANG"][1], qty=200, unit_price=250_000),
                                         dict(sku="GACH-O4", name=SKU["GACH-O4"][1], qty=34_000, unit_price=1_050)],
             unpaid=True, note="Quá hạn, đã xin nhà cung cấp gia hạn")
    add_bill(glass, date(2026, 9, 30), [dict(sku="KINH-10", name=SKU["KINH-10"][1], qty=100, unit_price=765_000),
                                        dict(sku="CUA-NHOM", name=SKU["CUA-NHOM"][1], qty=40, unit_price=1_290_000)],
             unpaid=True, note="Quá hạn, đang chờ khách thanh toán để trả")
    bills.sort(key=lambda b: (b["bill_date"], b["supplier"]["supplier_id"]))
    return suppliers, bills


def fixed_obligations():
    """Các khoản chi cố định hằng tháng (không có hóa đơn trong Odoo, kế toán nhập tay). Mỗi khoản có mức ưu tiên
    (1 = bắt buộc trả đúng hạn) và số ngày có thể hoãn. Mức phạt là GIẢ ĐỊNH cho demo."""
    out = []

    def add(kind, desc, amount, due, priority, defer, late_cost, to):
        if due > AS_OF:
            out.append(dict(kind=kind, description=desc, amount=int(amount), due_date=due.isoformat(), priority=priority,
                            can_defer_days=defer, late_cost=late_cost, counterparty=to))

    loan = 3_000 * M          # dư nợ tại 09/11/2026 (giả định)
    for y, m in [(2026, 11), (2026, 12), (2027, 1)]:
        add("payroll", f"Lương nhân viên tháng {m}", 180 * M, prev_workday(date(y, m, 25)), 1, 0,
            "Chậm lương làm mất nhân sự và vi phạm hợp đồng lao động", "Nhân viên Minh Phát")
        add("insurance", f"BHXH, BHYT, BHTN tháng {m}", 54 * M, next_workday(date(y, m, 28)), 1, 0,
            "Tiền chậm đóng khoảng 0,03% mỗi ngày (giả định)", "Cơ quan bảo hiểm xã hội")
        add("tax", f"Thuế GTGT tháng {m - 1 or 12}", 55 * M, next_workday(date(y, m, 20)), 1, 0,
            "Tiền chậm nộp khoảng 0,03% mỗi ngày (giả định)", "Cơ quan thuế")
        add("tax", f"Thuế TNCN tháng {m - 1 or 12}", 6 * M, next_workday(date(y, m, 20)), 1, 0,
            "Tiền chậm nộp khoảng 0,03% mỗi ngày (giả định)", "Cơ quan thuế")
        add("rent", f"Thuê kho và văn phòng tháng {m}", 55 * M, next_workday(date(y, m, 5)), 2, 5,
            "Có thể thương lượng gia hạn tối đa vài ngày", "Chủ kho, chủ văn phòng")
        add("utility", f"Điện, nước, viễn thông tháng {m}", 8 * M, next_workday(date(y, m, 8)), 3, 7,
            "Bị nhắc và có thể bị cắt dịch vụ sau hạn", "Nhà cung cấp điện nước, viễn thông")
        interest = int(loan * 0.095 / 12)
        add("loan", f"Trả nợ ngân hàng tháng {m} (gốc 60 triệu và lãi)", 60 * M + interest, next_workday(date(y, m, 25)), 1, 0,
            "Phạt chậm trả theo hợp đồng tín dụng, ảnh hưởng xếp hạng vay", "Ngân hàng")
        loan -= 60 * M
    add("insurance", "Bảo hiểm tài sản và xe tải quý 1/2027", 18 * M, date(2026, 12, 1), 3, 15,
        "Có thể dời ngày thanh toán theo thỏa thuận", "Công ty bảo hiểm")
    add("tax", "Thuế TNDN tạm nộp quý 4/2026", 90 * M, date(2027, 1, 30), 1, 0,
        "Tiền chậm nộp khoảng 0,03% mỗi ngày (giả định)", "Cơ quan thuế")
    add("payroll", "Thưởng Tết dương lịch và Tết Nguyên đán 2027", 260 * M, date(2027, 1, 28), 1, 0,
        "Chậm thưởng ảnh hưởng tinh thần và giữ chân nhân sự", "Nhân viên Minh Phát")
    return sorted(out, key=lambda o: (o["due_date"], o["priority"]))


def company_profile(rows, bill_out, obligations):
    """Hồ sơ tài chính của công ty tại AS_OF. Số dư tiền đầu kỳ được chỉnh để tuần 16/11 thiếu tiền nếu Tổng thầu Đại Phát
    trả chậm, còn nếu họ trả đúng hạn thì đủ. Số dư là GIẢ ĐỊNH cho demo (Odoo không giữ số dư ngân hàng thật)."""
    med = {}
    for r in rows:
        if r["pays"] and r["inv_date"] < AS_OF:
            med.setdefault(r["customer"]["name"], []).append((r["pays"][-1][0] - r["due"]).days)
    med = {k: float(np.median(v)) for k, v in med.items() if len(v) >= 5}

    def week(d):
        return d - timedelta(days=d.weekday())

    def flows(big_late):
        w = {}
        for r in rows:
            rem = r["amount"] - sum(a for _, a in r["pays"])
            if rem <= 0 or r["dispute"]:
                continue
            delay = med.get(r["customer"]["name"], 3)
            if r["customer"]["name"] == BIG_LATE:
                delay = 12 if big_late else 0
            when = max(r["due"] + timedelta(days=int(round(delay))), AS_OF + timedelta(days=1))
            w[week(when)] = w.get(week(when), 0) + rem
        out = {}
        for b in bill_out:
            when = max(date.fromisoformat(b["due_date"]), AS_OF + timedelta(days=1))
            out[week(when)] = out.get(week(when), 0) + b["remaining_amount"]
        for o in obligations:
            out[week(date.fromisoformat(o["due_date"]))] = out.get(week(date.fromisoformat(o["due_date"])), 0) + o["amount"]
        return w, out

    def run(cash0, big_late):
        w, out = flows(big_late)
        cash, res, wk = cash0, [], week(AS_OF + timedelta(days=1))
        for _ in range(8):
            cash += w.get(wk, 0) - out.get(wk, 0)
            res.append((wk.isoformat(), int(cash)))
            wk += timedelta(days=7)
        return res

    cash0 = 600 * M
    for cash0 in range(300 * M, 3_000 * M, 10 * M):         # số dư nhỏ nhất mà kịch bản "Đại Phát trả đúng hạn" không âm
        if min(c for _, c in run(cash0, False)) >= 100 * M:
            break
    return dict(as_of=AS_OF.isoformat(), currency="VND", opening_cash=cash0, min_reserve=100 * M, overdraft_limit=200 * M,
                headcount=22, monthly_payroll_net=180 * M, loan_outstanding=3_000 * M, loan_rate_pct_year=9.5,
                note="Số dư và hạn mức là giả định cho demo", preview_late=run(cash0, True), preview_on_time=run(cash0, False))


def write_csv(csvdir: Path, seed: dict, per_file: int = 400):
    """CSV để nạp bằng chức năng Nhập (Import) của Odoo: products.csv, partners.csv và invoices_1..N.csv (hóa đơn nháp,
    mỗi hóa đơn nhiều dòng). Tiêu đề cột là tên trường kỹ thuật nên không phụ thuộc ngôn ngữ giao diện. Cột id là ID ngoài
    (external ID): nhập lại cùng file sẽ cập nhật chứ không tạo trùng."""
    csvdir.mkdir(parents=True, exist_ok=True)
    for old in csvdir.glob("invoices_*.csv"):      # xóa file cũ nếu lần sinh trước nhiều file hơn
        old.unlink()
    with open(csvdir / "products.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "default_code", "list_price", "type"])
        for p in seed["products"]:
            w.writerow([f"product_{p['sku']}", p["name"], p["sku"], p["unit_price"], "consu"])
    with open(csvdir / "partners.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "ref", "email", "is_company"])
        for c in seed["customers"]:
            w.writerow([f"partner_{c['customer_id']}", c["name"], c["customer_id"], c["email"], "True"])
    head = ["id", "move_type", "partner_id/id", "ref", "invoice_date", "invoice_date_due", "narration",
            "invoice_line_ids/product_id/id", "invoice_line_ids/name", "invoice_line_ids/quantity", "invoice_line_ids/price_unit"]
    invs = seed["invoices"]
    for n, start in enumerate(range(0, len(invs), per_file), 1):
        with open(csvdir / f"invoices_{n}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            for i in invs[start:start + per_file]:
                for k, l in enumerate(i["lines"]):
                    first = [f"inv_{i['invoice_id']}", "out_invoice", f"partner_{i['customer_id']}", i["invoice_id"],
                             i["invoice_date"], i["due_date"], i["narration"]] if k == 0 else [""] * 7
                    w.writerow(first + [f"product_{l['sku']}", l["name"], l["qty"], l["unit_price"]])


def write(outdir: Path):
    customers, rows = build()
    suppliers, bills = build_ap(rows)
    outdir.mkdir(parents=True, exist_ok=True)
    seed_inv, inv_out, pay_out = [], [], []
    n_pay = 0
    inv_id = {}
    for i, r in enumerate(rows, 1):
        c = r["customer"]
        iid = f"INV-{i:04d}"
        inv_id[id(r)] = iid
        paid = sum(a for _, a in r["pays"])
        narration = ("[DISPUTE] " if r["dispute"] else "") + r["note"]
        seed_inv.append(dict(
            invoice_id=iid, customer_id=c["customer_id"], invoice_date=r["inv_date"].isoformat(),
            due_date=r["due"].isoformat(), amount=r["amount"], dispute=r["dispute"], narration=narration,
            lines=[dict(sku=l["sku"], name=l["name"], qty=l["qty"], unit_price=l["unit_price"]) for l in r["lines"]],
            payments=[dict(date=d.isoformat(), amount=a) for d, a in r["pays"]]))
        inv_out.append(dict(
            invoice_id=iid, customer_id=c["customer_id"], display_name=c["name"],
            due_date=r["due"].isoformat(), invoice_amount=r["amount"], remaining_amount=r["amount"] - paid,
            currency="VND", dispute_status="disputed" if r["dispute"] else "none", contact_email=c["email"]))
        for d, a in r["pays"]:
            n_pay += 1
            pay_out.append(dict(payment_id=f"PAY-{n_pay:04d}", invoice_id=iid, customer_id=c["customer_id"],
                                payment_date=d.isoformat(), amount=a))

    # Phía phải trả chỉ cần đủ cho demo: giữ hóa đơn mua còn nợ và hóa đơn trả trong khoảng 2 tháng gần đây
    bills = [b for b in bills if b["amount"] > sum(a for _, a in b["pays"]) or b["bill_date"] >= date(2026, 9, 10)]
    seed_bills, bill_out = [], []
    for k, b in enumerate(bills, 1):
        x = b["supplier"]
        bid = f"BILL-{k:04d}"
        note = b["note"]
        if b.get("link_row") is not None:
            note += f" (đơn {inv_id[id(b['link_row'])]})"
        paid = sum(a for _, a in b["pays"])
        seed_bills.append(dict(
            bill_id=bid, supplier_id=x["supplier_id"], bill_date=b["bill_date"].isoformat(), due_date=b["due"].isoformat(),
            amount=b["amount"], narration=note,
            lines=[dict(sku=l["sku"], name=l["name"], qty=l["qty"], unit_price=l["unit_price"]) for l in b["lines"]],
            payments=[dict(date=d.isoformat(), amount=a) for d, a in b["pays"]]))
        if b["amount"] - paid > 0:
            bill_out.append(dict(bill_id=bid, supplier_id=x["supplier_id"], display_name=x["name"], due_date=b["due"].isoformat(),
                                 bill_amount=b["amount"], remaining_amount=b["amount"] - paid, currency="VND",
                                 strategic=x["strategic"], late_fee_pct_month=x["late_fee"], note=note))

    seed = dict(
        products=[dict(sku=p[0], name=p[1], unit=p[2], unit_price=p[3]) for p in PRODUCTS],
        customers=[dict(customer_id=c["customer_id"], name=c["name"], email=c["email"]) for c in customers],
        suppliers=[dict(supplier_id=x["supplier_id"], name=x["name"], email=x["email"]) for x in suppliers],
        invoices=seed_inv, bills=seed_bills)
    obligations = fixed_obligations()
    company = company_profile(rows, bill_out, obligations)
    company["suppliers"] = [dict(supplier_id=x["supplier_id"], name=x["name"], terms_days=x["terms"], strategic=x["strategic"],
                                 late_fee_pct_month=x["late_fee"], stops_supply_if_late=x["strategic"]) for x in suppliers]
    write_csv(outdir / "csv", seed)
    for name, obj in [("seed_data", seed), ("invoices", inv_out), ("payments", pay_out), ("bills", bill_out),
                      ("obligations", obligations), ("company", company)]:
        (outdir / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    open_bills = sum(b["remaining_amount"] for b in bill_out)
    print(f"{len(customers)} khách, {len(rows)} hóa đơn, {n_pay} khoản thanh toán; {len(suppliers)} nhà cung cấp, "
          f"{len(bills)} hóa đơn mua, còn nợ {len(bill_out)} ({open_bills / 1e9:.2f} tỷ); {len(obligations)} khoản chi cố định -> {outdir}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "fixtures" / "demo_company"
    write(out)
