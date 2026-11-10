"""Controlled local-LLM wording for reminder drafts.

The model receives no invoice, customer, amount, date, or email data. It can
only suggest two generic Vietnamese sentences; backend inserts every fact.
"""
import json
import logging
import os
import re
from datetime import date
from urllib import error, request

from . import drafts
from .contracts import Invoice

log = logging.getLogger("thutien.drafts")
_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "request": {"type": "string"},
    },
    "required": ["intro", "request"],
    "additionalProperties": False,
}
_UNSAFE = re.compile(r"[\d{}<>@/$\\]|https?://|\b(?:vnd|usd|đồng|công ty|khách hàng)\b", re.IGNORECASE)


def _valid_sentence(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    sentence = value.strip()
    if not 15 <= len(sentence) <= 220 or "\n" in sentence or _UNSAFE.search(sentence):
        return None
    return sentence


def _ollama_sentences() -> tuple[str, str]:
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    payload = {
        "model": os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        "stream": False,
        "think": False,
        "format": _SCHEMA,
        "options": {"temperature": 0.2, "num_predict": 180},
        "messages": [
            {"role": "system", "content": (
                "Bạn chỉ viết lời nhắc thanh toán lịch sự bằng tiếng Việt. "
                "Trả JSON gồm intro và request, mỗi trường một câu ngắn, chung chung. "
                "Không viết tên người, tên công ty, mã hóa đơn, số tiền, ngày, email, URL, "
                "địa chỉ, lời đe dọa hoặc cam kết pháp lý. Không thêm thông tin thực tế."
            )},
            {"role": "user", "content": "Viết hai câu lịch sự để dùng trong bản nháp nhắc thanh toán, không có dữ liệu khách hàng."},
        ],
    }
    timeout = min(max(float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30")), 1), 60)
    req = request.Request(url, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    content = result["message"]["content"]
    suggestions = json.loads(content)
    if not isinstance(suggestions, dict) or set(suggestions) != {"intro", "request"}:
        raise ValueError("unexpected Ollama JSON fields")
    intro = _valid_sentence(suggestions["intro"])
    payment_request = _valid_sentence(suggestions["request"])
    if not intro or not payment_request:
        raise ValueError("Ollama wording contains facts or invalid text")
    return intro, payment_request


def generate(inv: Invoice, pay_by: date) -> tuple[str, str, str]:
    """Return subject, body, source; failures use a clearly labeled template."""
    subject, fallback_body = drafts.compose(inv, pay_by)
    if os.getenv("OLLAMA_ENABLED", "0") != "1":
        return subject, fallback_body, "template_fallback"
    try:
        intro, payment_request = _ollama_sentences()
    except (OSError, error.URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        log.warning("Ollama draft unavailable; using template: %s", exc)
        return subject, fallback_body, "template_fallback"
    body = "\n\n".join([
        f"Kính gửi {inv.display_name},",
        intro,
        f"Theo hồ sơ của chúng tôi, hóa đơn {inv.invoice_id} còn nợ "
        f"{drafts.vnd(inv.remaining_amount)} VND, hạn trả {drafts.dmy(inv.due_date)}.",
        f"{payment_request} Ngày đề nghị thanh toán: {drafts.dmy(pay_by)}. "
        "Nếu quý khách đã thanh toán, xin vui lòng bỏ qua thư này.",
        "Trân trọng,\nPhòng Kế toán",
    ])
    return subject, body, "ollama"
