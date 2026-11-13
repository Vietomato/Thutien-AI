"""Chat assistant endpoints. Read-only: the assistant can only call the tools in chat_tools."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import chat, chat_data
from .audit import append_audit
from .auth import require_permission
from .chat_tools import Toolbox
from .llm import LLMError, llm_from_env

router = APIRouter(prefix="/api/chat", tags=["chat"])

RATE_LIMIT = 15          # questions per user per minute
_recent: dict[str, deque] = defaultdict(deque)


class Message(BaseModel):
    role: str
    content: str = Field(max_length=2000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Message] = Field(default_factory=list, max_length=20)


def get_llm():
    return llm_from_env()


def _check_rate(username: str) -> None:
    now, window = time.monotonic(), _recent[username]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, "Hỏi quá nhanh, thử lại sau một phút.")
    window.append(now)


@router.get("/status", dependencies=[Depends(require_permission("forecast:read"))])
def status():
    llm = get_llm()
    return {"available": llm is not None, "provider": llm.name if llm else None}


@router.post("")
def ask(body: ChatIn, user: dict = Depends(require_permission("forecast:read"))):
    llm = get_llm()
    if llm is None:
        raise HTTPException(503, "Trợ lý chưa được cấu hình (cần OPENAI_API_KEY hoặc Ollama).")
    _check_rate(user["username"])
    try:
        result = chat.answer(llm, Toolbox(chat_data.load_snapshot()), body.question, [m.model_dump() for m in body.history])
    except LLMError as exc:
        if exc.rate_limited:
            append_audit(user["username"], "chat_failed", "chat", {"provider": llm.name, "reason": str(exc)[:200]})
            raise HTTPException(429, "Nhà cung cấp mô hình đang giới hạn lượt dùng. Đợi khoảng một phút rồi hỏi lại.") from None
        append_audit(user["username"], "chat_failed", "chat", {"provider": llm.name, "reason": str(exc)[:200]})
        raise HTTPException(502, "Trợ lý không trả lời được lúc này. Thử lại sau.") from None
    append_audit(user["username"], "chat_asked", "chat",
                 {"provider": llm.name, "model": result["model"], "question": body.question[:200],
                  "tools": [s["tool"] for s in result["steps"]], "verified": result["verified"]})
    return {**result, "provider": llm.name}
