"""Read-only tools the assistant can call. Every number the assistant says comes from one of these results.

The model chooses a tool and fills in its parameters; the code does the arithmetic (the same functions the product uses) and
returns plain data. No tool writes anything, and none runs free text as SQL or code.

Tool failures are returned as {"error": ..., "hint": ...} so the model can correct itself (a wrong customer name, a bad date)."""
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from . import analytics, whatif
from .chat_data import Snapshot
from .whatif import Scenario

MAX_ROWS = 30


class ToolError(Exception):
    def __init__(self, message: str, hint: str | None = None, **extra):
        super().__init__(message)
        self.message, self.hint, self.extra = message, hint, extra


# ---------------------------------------------------------------- small helpers

def fold(text: str) -> str:
    """Lower case without accents, so that "Đại Phát" and "dai phat" are the same."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", fold(text)) if t]


def to_int(value, name: str, default: int | None = None, lo: int | None = None, hi: int | None = None) -> int:
    if value is None or value == "":
        if default is None:
            raise ToolError(f"Thiếu tham số {name}.")
        return default
    try:
        number = int(round(float(str(value).replace(",", ".").strip())))
    except (TypeError, ValueError):
        raise ToolError(f"Tham số {name} phải là một số, nhận được: {value!r}.")
    if lo is not None and number < lo or hi is not None and number > hi:
        raise ToolError(f"Tham số {name} phải nằm trong khoảng {lo} đến {hi}, nhận được {number}.")
    return number


def to_date(value, name: str, as_of: date) -> date:
    text = str(value or "").strip()
    if not text:
        raise ToolError(f"Thiếu tham số {name}.")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", text)
    if m:
        day, month, year = int(m[1]), int(m[2]), m[3]
        try:
            if year:
                return date(int(year) + (2000 if len(year) == 2 else 0), month, day)
            guess = date(as_of.year, month, day)
            return guess if guess >= as_of - timedelta(days=180) else date(as_of.year + 1, month, day)
        except ValueError:
            pass
    raise ToolError(f"Không hiểu ngày {text!r} ở tham số {name}.", hint="Dùng định dạng YYYY-MM-DD hoặc dd/mm/yyyy.")


def limit_of(args: dict, default: int = 10) -> int:
    return to_int(args.get("limit"), "limit", default, 1, MAX_ROWS)


def days_between(a: date, b: date) -> int:
    return (b - a).days


# ---------------------------------------------------------------- the toolbox

class Toolbox:
    def __init__(self, snap: Snapshot):
        self.snap = snap
        self._open_by_customer: dict[str, list[dict]] = {}
        for row in snap.ranked:
            self._open_by_customer.setdefault(row["customer_id"], []).append(row)

    # ----- customers

    def _candidates(self, query: str) -> list[dict]:
        q = tokens(query)
        if not q:
            return []
        out = []
        for cid, name in self.snap.names.items():
            name_tokens = tokens(name)
            hits = sum(1 for t in q if t in name_tokens or t == fold(cid))
            if hits == 0:
                continue
            out.append({"customer_id": cid, "name": name, "all_words_match": hits == len(q), "_score": (hits / len(q), -len(name_tokens))})
        out.sort(key=lambda c: c["_score"], reverse=True)
        return out

    def resolve_customer(self, ref) -> str:
        text = str(ref or "").strip()
        if not text:
            raise ToolError("Thiếu khách hàng.")
        for cid in self.snap.names:
            if cid.lower() == text.lower():
                return cid
        cands = self._candidates(text)
        full = [c for c in cands if c["all_words_match"]]
        exact = [c for c in full if fold(c["name"]) == fold(text)]
        if len(exact) == 1:
            return exact[0]["customer_id"]
        if len(full) == 1:
            return full[0]["customer_id"]
        if len(full) > 1:
            raise ToolError(f"Có {len(full)} khách hàng khớp với {text!r}.", hint="Hỏi lại người dùng muốn nói khách nào.",
                            candidates=[{"customer_id": c["customer_id"], "name": c["name"]} for c in full[:6]])
        if cands:
            raise ToolError(f"Không có khách hàng nào khớp hoàn toàn với {text!r}.", hint="Có thể người dùng muốn một trong các khách gần giống.",
                            candidates=[{"customer_id": c["customer_id"], "name": c["name"]} for c in cands[:5]])
        raise ToolError(f"Không tìm thấy khách hàng {text!r}.", hint="Dùng search_customers để tìm.")

    def search_customers(self, args: dict) -> dict:
        found = [{"customer_id": c["customer_id"], "name": c["name"], "all_words_match": c["all_words_match"],
                  "open_invoices": len(self._open_by_customer.get(c["customer_id"], [])),
                  "open_amount": sum(r["remaining_amount"] for r in self._open_by_customer.get(c["customer_id"], []))}
                 for c in self._candidates(str(args.get("query", "")))[:limit_of(args, 5)]]
        return {"query": args.get("query"), "matches": found}

    def get_customer(self, args: dict) -> dict:
        cid = self.resolve_customer(args.get("customer"))
        rows = self._open_by_customer.get(cid, [])
        history = sorted(d for c, d in self.snap.delays if c == cid)
        overdue = [r for r in rows if r["days_overdue"] > 0 and r["dispute_status"] != "disputed"]
        profile = {"customer_id": cid, "name": self.snap.names.get(cid, cid), "as_of": self.snap.as_of.isoformat(),
                   "open_invoices": len(rows), "open_amount": sum(r["remaining_amount"] for r in rows),
                   "overdue_invoices": len(overdue), "overdue_amount": sum(r["remaining_amount"] for r in overdue),
                   "disputed_invoices": sum(1 for r in rows if r["dispute_status"] == "disputed"),
                   "payment_history": None}
        if history:
            profile["payment_history"] = {
                "paid_invoices": len(history), "share_paid_late": round(sum(1 for d in history if d > 0) / len(history), 3),
                "days_late_p25": round(analytics.percentile(history, 0.25)), "days_late_median": round(analytics.percentile(history, 0.5)),
                "days_late_p75": round(analytics.percentile(history, 0.75)), "earliest": history[0], "latest": history[-1],
                "enough_history": len(history) >= analytics.MIN_HISTORY}
        biggest = sorted(rows, key=lambda r: -r["remaining_amount"])[:5]
        profile["biggest_open_invoices"] = [self._invoice_row(r) for r in biggest]
        return profile

    # ----- invoices

    def _invoice_row(self, r: dict) -> dict:
        pred = r.get("prediction")
        due = date.fromisoformat(r["due_date"])
        predicted = None
        if pred:
            usual = date.fromisoformat(pred["predicted_date_p50"])
            predicted = {"early": pred["predicted_date_p25"], "usual": pred["predicted_date_p50"], "late": pred["predicted_date_p75"],
                         "usual_delay_days_after_due": days_between(due, usual),
                         "basis": {"customer_median": "lịch sử của chính khách", "global_median": "lịch sử chung (khách ít lịch sử)",
                                   "no_history": "chưa có lịch sử"}.get(pred["method"], pred["method"]),
                         "paid_invoices_behind_it": pred["history_count"], "adjusted_because_already_later_than_history": pred["overdue_adjusted"]}
        status = "disputed" if r["dispute_status"] == "disputed" else "overdue" if r["days_overdue"] > 0 else "not_due"
        return {"invoice_id": r["invoice_id"], "customer_id": r["customer_id"], "customer": r["display_name"], "remaining_amount": r["remaining_amount"],
                "due_date": r["due_date"], "days_overdue": r["days_overdue"], "status": status, "priority_rank": r["rank"],
                "priority_score": int(Decimal(r["priority_score"])), "hold_reasons": r["hold_reasons"], "predicted": predicted}

    def list_invoices(self, args: dict) -> dict:
        rows = self.snap.ranked
        if args.get("customer"):
            rows = self._open_by_customer.get(self.resolve_customer(args["customer"]), [])
        status = str(args.get("status") or "all")
        if status not in {"all", "overdue", "not_due", "disputed"}:
            raise ToolError(f"status không hợp lệ: {status!r}.", hint="Dùng all, overdue, not_due hoặc disputed.")
        if status == "overdue":
            rows = [r for r in rows if r["days_overdue"] > 0 and r["dispute_status"] != "disputed"]
        elif status == "not_due":
            rows = [r for r in rows if r["days_overdue"] <= 0 and r["dispute_status"] != "disputed"]
        elif status == "disputed":
            rows = [r for r in rows if r["dispute_status"] == "disputed"]
        if args.get("min_amount") not in (None, ""):
            rows = [r for r in rows if r["remaining_amount"] >= to_int(args["min_amount"], "min_amount")]
        if args.get("max_amount") not in (None, ""):
            rows = [r for r in rows if r["remaining_amount"] <= to_int(args["max_amount"], "max_amount")]
        if args.get("due_before"):
            rows = [r for r in rows if date.fromisoformat(r["due_date"]) <= to_date(args["due_before"], "due_before", self.snap.as_of)]
        sort_by = str(args.get("sort_by") or "priority")
        far = date.max.isoformat()
        keys = {"priority": lambda r: r["rank"], "amount": lambda r: -r["remaining_amount"], "days_overdue": lambda r: -r["days_overdue"],
                "due_date": lambda r: r["due_date"], "predicted_date": lambda r: (r["prediction"] or {}).get("predicted_date_p50", far),
                "expected_delay": lambda r: -days_between(date.fromisoformat(r["due_date"]), date.fromisoformat((r["prediction"] or {}).get("predicted_date_p50", r["due_date"])))}
        if sort_by not in keys:
            raise ToolError(f"sort_by không hợp lệ: {sort_by!r}.", hint="Dùng " + ", ".join(keys) + ".")
        rows = sorted(rows, key=keys[sort_by])
        limit = limit_of(args)
        return {"as_of": self.snap.as_of.isoformat(), "matching_invoices": len(rows), "matching_amount": sum(r["remaining_amount"] for r in rows),
                "shown": min(limit, len(rows)), "sorted_by": sort_by, "invoices": [self._invoice_row(r) for r in rows[:limit]]}

    def get_invoice(self, args: dict) -> dict:
        ref = str(args.get("invoice_id") or "").strip()
        match = [r for r in self.snap.ranked if r["invoice_id"].lower() == ref.lower()] or \
                [r for r in self.snap.ranked if ref and r["invoice_id"].lower().endswith(ref.lower())]
        if len(match) != 1:
            raise ToolError(f"Không xác định được hóa đơn {ref!r}.", hint="Dùng list_invoices để tìm mã hóa đơn.",
                            candidates=[r["invoice_id"] for r in match[:5]])
        r = match[0]
        row = self._invoice_row(r)
        row["late_rate"] = round(float(r["late_rate"]), 3)
        row["late_rate_basis"] = r["late_rate_source"]
        row["score_formula"] = "số tiền còn nợ × tỷ lệ trả trễ × số ngày quá hạn"
        row["has_pending_draft"] = r["invoice_id"] in self.snap.pending_draft_invoices
        return row

    # ----- forecast

    def _week_label(self, i: int) -> dict:
        start = self.snap.weeks[i].week_start
        return {"week": i + 1, "week_start": start.isoformat(), "week_end": (start + timedelta(days=6)).isoformat()}

    def get_overview(self, args: dict) -> dict:
        weeks = self.snap.weeks
        info = analytics.summarize(self.snap.invoices, self.snap.as_of)
        return {"as_of": self.snap.as_of.isoformat(), "data_source": self.snap.source, "receivables": info,
                "forecast_12_weeks": {**whatif.summarize(weeks), "expected_receipts": sum(w.receipt_expected or 0 for w in weeks),
                                      "early_scenario_receipts": sum(w.receipt_p25 for w in weeks), "late_scenario_receipts": sum(w.receipt_p75 for w in weeks),
                                      "outgoings": sum(w.obligations for w in weeks)},
                "outgoings_known": {"supplier_bills_in_odoo": sum(1 for o in self.snap.outgoings if o.source == "odoo"),
                                    "typed_by_accountants": sum(1 for o in self.snap.outgoings if o.source == "manual")},
                "reminder_drafts_waiting_for_approval": len(self.snap.pending_draft_invoices)}

    def get_forecast(self, args: dict) -> dict:
        first, last = to_int(args.get("from_week"), "from_week", 1, 1, analytics.WEEKS), to_int(args.get("to_week"), "to_week", analytics.WEEKS, 1, analytics.WEEKS)
        if first > last:
            raise ToolError("from_week phải nhỏ hơn hoặc bằng to_week.")
        rows = []
        for i in range(first - 1, last):
            w = self.snap.weeks[i]
            rows.append({**self._week_label(i), "receipts_early_scenario": w.receipt_p25, "receipts_expected": w.receipt_expected,
                         "receipts_late_scenario": w.receipt_p75, "outgoings": w.obligations, "shortfall_if_customers_pay_late": w.gap_p75})
        return {"as_of": self.snap.as_of.isoformat(), "weeks": rows, "summary_all_12_weeks": whatif.summarize(self.snap.weeks),
                "note": "Thiếu = chi trừ thu ở kịch bản khách trả muộn. Không phải số dư tiền mặt."}

    def get_week_detail(self, args: dict) -> dict:
        week = to_int(args.get("week"), "week", None, 1, analytics.WEEKS)
        detail = analytics.week_contributions(self.snap.invoices, self.snap.delays, self.snap.as_of, top=min(limit_of(args, 8), 15))[week - 1]
        w = self.snap.weeks[week - 1]
        due_now = [o for o in self.snap.outgoings if whatif.week_index(o.due_date, self.snap.as_of) == week - 1]
        return {**self._week_label(week - 1), "receipts_expected": w.receipt_expected, "receipts_early_scenario": w.receipt_p25,
                "receipts_late_scenario": w.receipt_p75, "outgoings": w.obligations, "shortfall_if_customers_pay_late": w.gap_p75,
                "invoices_behind_expected_receipts": detail["items"], "other_invoices_count": detail["more_count"], "other_invoices_amount": detail["more_amount"],
                "outgoings_due_this_week": [self._outgoing_row(o) for o in sorted(due_now, key=lambda o: -o.amount)[:10]], "outgoings_due_this_week_count": len(due_now)}

    def _outgoing_row(self, o: whatif.Outgoing) -> dict:
        return {"outgoing": o.key, "source": "Odoo" if o.source == "odoo" else "kế toán nhập tay", "description": o.description, "amount": o.amount,
                "due_date": o.due_date.isoformat(), "week": whatif.week_index(o.due_date, self.snap.as_of) + 1,
                "late_fee_percent_per_month": o.fee_pct_per_month, "late_fee_known": o.fee_pct_per_month is not None}

    def list_outgoings(self, args: dict) -> dict:
        rows = self.snap.outgoings
        if args.get("source"):
            source = {"odoo": "odoo", "manual": "manual"}.get(str(args["source"]).lower())
            if not source:
                raise ToolError("source phải là odoo hoặc manual.")
            rows = [o for o in rows if o.source == source]
        if args.get("from_date"):
            rows = [o for o in rows if o.due_date >= to_date(args["from_date"], "from_date", self.snap.as_of)]
        if args.get("to_date"):
            rows = [o for o in rows if o.due_date <= to_date(args["to_date"], "to_date", self.snap.as_of)]
        if args.get("min_amount") not in (None, ""):
            rows = [o for o in rows if o.amount >= to_int(args["min_amount"], "min_amount")]
        order = str(args.get("sort_by") or "due_date")
        rows = sorted(rows, key=(lambda o: -o.amount) if order == "amount" else (lambda o: (o.due_date, -o.amount)))
        limit = limit_of(args, 15)
        return {"matching": len(rows), "matching_amount": sum(o.amount for o in rows), "shown": min(limit, len(rows)),
                "outgoings": [self._outgoing_row(o) for o in rows[:limit]],
                "note": "Hóa đơn nhà cung cấp trong Odoo chỉ có ngày đến hạn và số tiền (không có tên nhà cung cấp, không có điều khoản phạt). "
                        "Phí phạt chỉ có ở khoản kế toán nhập tay khi kế toán điền."}

    # ----- scenarios

    def what_if(self, args: dict) -> dict:
        as_of = self.snap.as_of
        scenario, assumptions, affected = Scenario(), [], []
        for item in args.get("customer_delays") or []:
            cid = self.resolve_customer(item.get("customer"))
            days = to_int(item.get("extra_days"), "extra_days", None, -365, 365)
            scenario.customer_shifts[cid] = scenario.customer_shifts.get(cid, 0) + days
            rows = [r for r in self._open_by_customer.get(cid, []) if r["dispute_status"] != "disputed"]
            affected.append({"customer_id": cid, "name": self.snap.names.get(cid, cid), "extra_days": days, "open_invoices_affected": len(rows),
                             "amount_affected": sum(r["remaining_amount"] for r in rows)})
            assumptions.append(f"Mọi ngày trả dự đoán của {self.snap.names.get(cid, cid)} dịch {'chậm thêm' if days >= 0 else 'sớm hơn'} {abs(days)} ngày.")
        for ref in args.get("customers_pay_now") or []:
            cid = self.resolve_customer(ref)
            scenario.pay_now.add(cid)
            rows = [r for r in self._open_by_customer.get(cid, []) if r["dispute_status"] != "disputed"]
            affected.append({"customer_id": cid, "name": self.snap.names.get(cid, cid), "pays_everything_this_week": True,
                             "open_invoices_affected": len(rows), "amount_affected": sum(r["remaining_amount"] for r in rows)})
            assumptions.append(f"{self.snap.names.get(cid, cid)} trả hết các hóa đơn đang mở ngay trong tuần này.")
        every = args.get("all_customers_extra_days")
        if every not in (None, "", 0, "0"):
            days = to_int(every, "all_customers_extra_days", None, -365, 365)
            for cid in {i.customer_id for i in self.snap.invoices}:
                scenario.customer_shifts[cid] = scenario.customer_shifts.get(cid, 0) + days
            assumptions.append(f"Tất cả khách hàng trả {'chậm thêm' if days >= 0 else 'sớm hơn'} {abs(days)} ngày so với dự đoán.")
        known = {o.key: o for o in self.snap.outgoings}
        for item in args.get("defer") or []:
            key = str(item.get("outgoing") or "").strip()
            if key not in known:
                raise ToolError(f"Không có khoản chi {key!r}.", hint="Dùng list_outgoings để lấy mã khoản chi. Một số mã hiện có: " + ", ".join(list(known)[:6]) + ".")
            days = to_int(item.get("days"), "days", None, 1, 365)
            scenario.defer[key] = days
            o = known[key]
            assumptions.append(f"Khoản chi {o.description} ({o.amount:,} đ, hạn {o.due_date.strftime('%d/%m/%Y')}) được trả muộn {days} ngày.".replace(",", "."))
        for item in args.get("extra_outgoings") or []:
            amount = to_int(item.get("amount"), "amount", None, 1)
            due = to_date(item.get("due_date"), "due_date", as_of)
            label = str(item.get("label") or "khoản chi giả định")
            scenario.extra_outgoings.append((due, amount, label))
            assumptions.append(f"Thêm khoản chi giả định {label}: {amount:,} đ vào ngày {due.strftime('%d/%m/%Y')}.".replace(",", "."))
        if scenario.is_empty():
            raise ToolError("Kịch bản trống: chưa có thay đổi nào để thử.",
                            hint="Điền ít nhất một trong customer_delays, customers_pay_now, all_customers_extra_days, defer, extra_outgoings.")
        after = whatif.run_forecast(self.snap.invoices, self.snap.delays, self.snap.outgoings, as_of, scenario)
        result = {"as_of": as_of.isoformat(), "assumptions": assumptions, "affected": affected, **whatif.compare(self.snap.weeks, after)}
        notes = []
        if affected and all(a.get("open_invoices_affected", 1) == 0 for a in affected) and not (scenario.defer or scenario.extra_outgoings or every):
            notes.append("Khách hàng này hiện không có hóa đơn nào đang mở (hoặc chỉ có hóa đơn tranh chấp), nên kịch bản không làm thay đổi dự báo.")
        if not result["changed_weeks"]:
            notes.append("Kịch bản không làm thay đổi tuần nào trong 12 tuần dự báo.")
        result["notes"] = notes
        result["how_to_read"] = "Thiếu = chi trừ thu ở kịch bản khách trả muộn (cách cảnh báo của hệ thống). Dự báo chỉ gồm các hóa đơn đang mở."
        return result

    def defer_options(self, args: dict) -> dict:
        days = to_int(args.get("defer_days"), "defer_days", 14, 1, 180)
        result = whatif.defer_options(self.snap.invoices, self.snap.delays, self.snap.outgoings, self.snap.as_of, days, top=min(limit_of(args, 8), 15))
        result["note"] = ("Phí phạt chỉ có ở khoản kế toán nhập tay khi kế toán điền. Hóa đơn nhà cung cấp trong Odoo không có điều khoản phạt, "
                          "nên với chúng hệ thống không biết hoãn có bị phạt hay không.")
        return result

    # ----- explanations

    def explain_method(self, args: dict) -> dict:
        topics = {
            "prediction": ("Dự đoán ngày trả: với mỗi hóa đơn đang mở, lấy các lần khách đó đã trả trễ bao nhiêu ngày so với hạn. P25, P50, P75 của dãy đó "
                           "cộng vào hạn trả cho ra ngày trả sớm, thường lệ và muộn. Khách có dưới 5 hóa đơn đã trả thì dùng lịch sử chung và được gắn nhãn "
                           "độ tin cậy thấp. Hóa đơn đã quá hạn chỉ dùng các lần trả trước còn trễ hơn mức đó. Hóa đơn tranh chấp không được dự đoán."),
            "priority": "Điểm ưu tiên thu nợ = số tiền còn nợ × tỷ lệ các lần trước khách trả trễ × số ngày quá hạn. Điểm càng cao càng nên nhắc sớm.",
            "forecast": ("Dự báo 12 tuần: cộng tiền các hóa đơn đang mở vào tuần dự kiến khách trả, rồi so với tiền phải chi (hóa đơn nhà cung cấp trong Odoo cộng "
                         "khoản kế toán nhập tay). Cảnh báo thiếu tiền dùng kịch bản khách trả muộn."),
            "scenarios": ("Ba kịch bản (sớm, thường lệ, muộn) là phép thử sức chịu đựng, không phải khoảng tin cậy thống kê: mỗi hóa đơn được đặt ở ngày sớm, "
                          "thường lệ hoặc muộn của riêng nó. Kịch bản thường lệ hiển thị là số kỳ vọng."),
            "expected": ("Số kỳ vọng: mỗi hóa đơn được chia vào các tuần khách có thể trả, theo xác suất rút ra từ lịch sử trả của khách đó "
                         "(pha nhẹ với lịch sử chung). Trên dữ liệu kiểm thử công khai, cách này sai lệch theo tuần ít hơn cách dồn cả hóa đơn vào một ngày."),
            "limits": ("Giới hạn: dự báo chỉ gồm hóa đơn đang mở, không dự đoán hóa đơn sẽ phát sinh. Chi chỉ có hai nguồn: hóa đơn nhà cung cấp trong Odoo và khoản kế toán "
                       "nhập tay. Không phải số dư tiền mặt. Dữ liệu demo là dữ liệu giả lập."),
        }
        topic = str(args.get("topic") or "").strip().lower()
        if topic not in topics:
            raise ToolError(f"Chủ đề không có: {topic!r}.", hint="Dùng một trong: " + ", ".join(topics))
        return {"topic": topic, "explanation": topics[topic],
                "constants": {"min_paid_invoices_for_own_history": analytics.MIN_HISTORY, "forecast_weeks": analytics.WEEKS}}

    # ----- dispatch

    def call(self, name: str, args: dict | None) -> dict:
        handler = getattr(self, name, None)
        if name not in TOOL_NAMES or handler is None:
            return {"error": f"Không có công cụ {name!r}.", "hint": "Chỉ dùng các công cụ được cung cấp."}
        try:
            return handler(args or {})
        except ToolError as exc:
            return {"error": exc.message, **({"hint": exc.hint} if exc.hint else {}), **exc.extra}
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            return {"error": f"Tham số không hợp lệ: {exc}", "hint": "Kiểm tra lại kiểu và tên tham số."}


# ---------------------------------------------------------------- what the model is shown

def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


_STR, _INT = {"type": "string"}, {"type": "integer"}
TOOL_SPECS = [
    {"name": "get_overview", "description": "Tổng quan: tổng công nợ, quá hạn, tranh chấp, số tuần có nguy cơ thiếu tiền, tuần nặng nhất, tổng thu và chi 12 tuần, số nháp chờ duyệt. Dùng cho câu hỏi chung về tình hình.", "parameters": _obj({})},
    {"name": "search_customers", "description": "Tìm khách hàng theo tên (không cần dấu, một phần tên cũng được) và cho biết mã khách, số hóa đơn mở.", "parameters": _obj({"query": _STR, "limit": _INT}, ["query"])},
    {"name": "get_customer", "description": "Hồ sơ một khách: công nợ đang mở, quá hạn, tranh chấp, thói quen trả tiền (số lần trả, tỷ lệ trễ, trung vị và P25/P75 số ngày trễ) và các hóa đơn lớn nhất. Nhận tên hoặc mã khách.", "parameters": _obj({"customer": _STR}, ["customer"])},
    {"name": "list_invoices", "description": "Liệt kê hóa đơn đang mở, có lọc và sắp xếp, kèm ngày trả dự đoán và độ tin cậy. status: all, overdue, not_due, disputed. sort_by: priority, amount, days_overdue, due_date, predicted_date, expected_delay (dự kiến trả trễ nhiều ngày nhất).", "parameters": _obj({"customer": _STR, "status": {"type": "string", "enum": ["all", "overdue", "not_due", "disputed"]}, "sort_by": {"type": "string", "enum": ["priority", "amount", "days_overdue", "due_date", "predicted_date", "expected_delay"]}, "min_amount": _INT, "max_amount": _INT, "due_before": {"type": "string", "description": "YYYY-MM-DD"}, "limit": _INT})},
    {"name": "get_invoice", "description": "Chi tiết một hóa đơn theo mã: điểm ưu tiên và cách tính, dự đoán ngày trả, lý do chưa nhắc được.", "parameters": _obj({"invoice_id": _STR}, ["invoice_id"])},
    {"name": "get_forecast", "description": "Dự báo từng tuần (tuần 1 bắt đầu từ ngày tính toán): thu ở kịch bản sớm, kỳ vọng, muộn; chi; số thiếu nếu khách trả muộn. Có thể giới hạn từ tuần nào đến tuần nào.", "parameters": _obj({"from_week": _INT, "to_week": _INT})},
    {"name": "get_week_detail", "description": "Vì sao một tuần có số thu đó: các hóa đơn góp vào (kèm xác suất khách trả trong tuần) và các khoản chi đến hạn trong tuần.", "parameters": _obj({"week": {"type": "integer", "description": "1 đến 12"}, "limit": _INT}, ["week"])},
    {"name": "list_outgoings", "description": "Các khoản phải chi: hóa đơn nhà cung cấp trong Odoo (chỉ có hạn và số tiền, mã bill:N) và khoản kế toán nhập tay (mã manual:N, có thể có phí phạt trả chậm nếu kế toán điền).", "parameters": _obj({"source": {"type": "string", "enum": ["odoo", "manual"]}, "from_date": _STR, "to_date": _STR, "min_amount": _INT, "sort_by": {"type": "string", "enum": ["due_date", "amount"]}, "limit": _INT})},
    {"name": "what_if", "description": "Thử một kịch bản 'nếu' rồi tính lại dự báo bằng đúng code của hệ thống và so với hiện tại. Có thể kết hợp: khách trả chậm/sớm thêm N ngày, khách trả hết ngay, mọi khách trễ thêm N ngày, hoãn khoản chi N ngày, thêm khoản chi giả định. Trả về tuần nào thiếu thêm, hết thiếu, số tiền thiếu trước và sau.", "parameters": _obj({"customer_delays": {"type": "array", "items": _obj({"customer": _STR, "extra_days": _INT}, ["customer", "extra_days"])}, "customers_pay_now": {"type": "array", "items": _STR}, "all_customers_extra_days": _INT, "defer": {"type": "array", "items": _obj({"outgoing": _STR, "days": _INT}, ["outgoing", "days"])}, "extra_outgoings": {"type": "array", "items": _obj({"amount": _INT, "due_date": _STR, "label": _STR}, ["amount", "due_date"])}})},
    {"name": "defer_options", "description": "Nếu hoãn từng khoản chi thêm N ngày thì số thiếu giảm bao nhiêu, và phí phạt ước tính nếu đã biết. Dùng cho câu hỏi 'hoãn khoản nào', 'khoản nào ít bị phạt nhất'. Nhớ: hóa đơn Odoo không có thông tin phạt.", "parameters": _obj({"defer_days": _INT, "limit": _INT})},
    {"name": "explain_method", "description": "Giải thích cách hệ thống tính. topic: prediction, priority, forecast, scenarios, expected, limits.", "parameters": _obj({"topic": {"type": "string", "enum": ["prediction", "priority", "forecast", "scenarios", "expected", "limits"]}}, ["topic"])},
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}
