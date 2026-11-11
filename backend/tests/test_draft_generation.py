import io
import json
from datetime import date
from urllib.error import URLError

from app import draft_generation, drafts
from app.contracts import Invoice


def _invoice(name="Khách hàng A"):
    return Invoice(invoice_id="INV-TEST", customer_id="C001", display_name=name,
                   due_date=date(2026, 10, 10), invoice_amount=120_000_000,
                   remaining_amount=120_000_000, dispute_status="none",
                   contact_email="customer@example.test")


def _response(content):
    return io.BytesIO(json.dumps({"message": {"content": json.dumps(content, ensure_ascii=False)}}).encode())


def test_local_model_only_writes_generic_wording(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "1")
    seen = {}

    def fake_urlopen(req, timeout):
        seen["request"] = json.loads(req.data)
        seen["timeout"] = timeout
        return _response({"intro": "Chúng tôi xin phép gửi lời nhắc thanh toán đến quý khách.",
                          "request": "Rất mong quý khách sắp xếp thanh toán khi thuận tiện."})

    monkeypatch.setattr(draft_generation.request, "urlopen", fake_urlopen)
    _, body, source = draft_generation.generate(_invoice(), date(2026, 11, 14))
    assert source == "ollama"
    assert "Khách hàng A" in body and "120.000.000" in body
    assert "10/10/2026" in body and "14/11/2026" in body
    sent = json.dumps(seen["request"], ensure_ascii=False)
    for fact in ("Khách hàng A", "INV-TEST", "120000000", "customer@example.test", "10/10/2026"):
        assert fact not in sent
    assert seen["request"]["format"]["additionalProperties"] is False


def test_invalid_model_facts_use_labeled_fallback(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "1")
    monkeypatch.setattr(draft_generation.request, "urlopen", lambda req, timeout: _response({
        "intro": "Kính gửi Khách hàng B, số tiền 999.000 VND.",
        "request": "Vui lòng thanh toán ngày 01/01/2027.",
    }))
    inv = _invoice()
    subject, body, source = draft_generation.generate(inv, date(2026, 11, 14))
    assert source == "template_fallback"
    assert (subject, body) == drafts.compose(inv, date(2026, 11, 14))


def test_offline_or_disabled_model_falls_back(monkeypatch):
    inv = _invoice()
    monkeypatch.setenv("OLLAMA_ENABLED", "1")

    def unavailable(req, timeout):
        raise URLError("offline")

    monkeypatch.setattr(draft_generation.request, "urlopen", unavailable)
    assert draft_generation.generate(inv, inv.due_date)[2] == "template_fallback"
    monkeypatch.setenv("OLLAMA_ENABLED", "0")
    assert draft_generation.generate(inv, inv.due_date)[2] == "template_fallback"
