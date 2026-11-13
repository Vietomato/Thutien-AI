"""Thin clients for a tool-calling language model: the OpenAI (ChatGPT) API or a local Ollama model, behind one interface.

The assistant talks to `LLMClient.complete(system, messages, tools)` and never to a provider directly. Messages use one neutral shape:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}
  {"role": "tool", "results": [{"id": str, "name": str, "content": str}]}      # the answers to the previous tool_calls
Each client turns that into its provider's format. Only the standard library is used (no SDK to install).

Which model is used is configuration, read from the environment:
  CHAT_PROVIDER      openai | groq | ollama | off       (default: openai if OPENAI_API_KEY is set, else ollama if OLLAMA_ENABLED=1, else off)
  OPENAI_API_KEY     the key; CHAT_MODEL (default gpt-4o-mini, any chat model with tool calling works); OPENAI_BASE_URL (default https://api.openai.com/v1)
  GROQ_API_KEY       Groq (OpenAI-compatible, fast); CHAT_MODEL default openai/gpt-oss-120b
  OLLAMA_URL, OLLAMA_MODEL (default qwen3:4b)       the same variables the reminder-draft wording already uses
  CHAT_TIMEOUT_SECONDS (default 60)
With OpenAI the question and the tool results (customer names, amounts) leave this machine; with Ollama they do not."""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib import error, request


class LLMError(Exception):
    """The model could not be reached or answered something unusable. The message never contains the API key."""

    def __init__(self, message: str, rate_limited: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.rate_limited, self.retry_after = rate_limited, retry_after


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn: ...


def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "CashPilot/1.0", **headers}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
            detail = json.loads(raw).get("error", {})
            detail = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:
            detail = raw.decode("utf-8", "replace")[:160].strip()      # e.g. a proxy's plain-text block page
        retry = exc.headers.get("Retry-After") if exc.headers else None
        try:
            retry_after = float(retry) if retry else None
        except ValueError:
            retry_after = None
        raise LLMError(f"HTTP {exc.code} {detail or exc.reason}".strip(), rate_limited=exc.code == 429, retry_after=retry_after) from None
    except (error.URLError, OSError, TimeoutError) as exc:
        raise LLMError(f"không kết nối được: {getattr(exc, 'reason', exc)}") from None
    except json.JSONDecodeError:
        raise LLMError("phản hồi không phải JSON") from None


class OpenAIClient:
    """OpenAI Chat Completions with function calling; Groq speaks the same protocol (name="groq")."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", timeout: float = 60, max_tokens: int = 4000,
                 name: str = "openai"):
        self.name = name
        self.api_key, self.model, self.base_url, self.timeout, self.max_tokens = api_key, model, base_url.rstrip("/"), timeout, max_tokens

    @staticmethod
    def convert(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                item = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    item["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                                          for c in m["tool_calls"]]
                out.append(item)
            elif m["role"] == "tool":
                out += [{"role": "tool", "tool_call_id": r["id"], "content": r["content"]} for r in m["results"]]
        return out

    def _send(self, url: str, payload: dict, headers: dict) -> dict:
        """One retry when the per-minute token limit is hit: the provider says how long to wait (capped, so a request never hangs)."""
        try:
            return _post(url, payload, headers, self.timeout)
        except LLMError as exc:
            if not exc.rate_limited:
                raise
            time.sleep(min(max(exc.retry_after or 8, 1), 20))
            return _post(url, payload, headers, self.timeout)

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        payload = {"model": self.model, "max_completion_tokens": self.max_tokens, "messages": self.convert(system, messages), "tool_choice": "auto",
                   "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]}
        if self.model.startswith("openai/gpt-oss"):      # reasoning model on Groq: keep the thinking short, it counts toward max_completion_tokens
            payload["reasoning_effort"] = "low"
        data = self._send(f"{self.base_url}/chat/completions", payload, {"Authorization": f"Bearer {self.api_key}"})
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("phản hồi không có lựa chọn nào")
        message = choices[0].get("message") or {}
        turn = Turn(text=message.get("content") or "")
        for i, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            turn.tool_calls.append(ToolCall(id=str(call.get("id") or f"call_{i}"), name=str(fn.get("name")), arguments=args if isinstance(args, dict) else {}))
        return turn


class OllamaClient:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    @staticmethod
    def convert(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                item = {"role": "assistant", "content": m.get("content", "")}
                if m.get("tool_calls"):
                    item["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}} for c in m["tool_calls"]]
                out.append(item)
            elif m["role"] == "tool":
                out += [{"role": "tool", "content": r["content"], "tool_name": r["name"]} for r in m["results"]]
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        payload = {"model": self.model, "stream": False, "think": False, "options": {"temperature": 0.1},
                   "messages": self.convert(system, messages),
                   "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]}
        data = _post(f"{self.base_url}/api/chat", payload, {"ngrok-skip-browser-warning": "1"}, self.timeout)   # harmless elsewhere; stops the ngrok free-tier interstitial
        message = data.get("message") or {}
        turn = Turn(text=message.get("content") or "")
        for i, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            turn.tool_calls.append(ToolCall(id=f"call_{i}", name=str(fn.get("name")), arguments=args if isinstance(args, dict) else {}))
        return turn


class ScriptedLLM:
    """For tests: plays back prepared turns (or functions of the messages) and records what it was asked."""
    name = "scripted"
    model = "scripted"

    def __init__(self, turns: list):
        self.turns, self.calls = list(turns), []

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        if not self.turns:
            raise LLMError("scripted model has no more turns")
        turn = self.turns.pop(0)
        return turn(messages) if callable(turn) else turn


def llm_from_env(env: dict | None = None) -> LLMClient | None:
    """The configured model, or None when no model is configured (the assistant then says so instead of guessing)."""
    env = os.environ if env is None else env
    timeout = min(max(float(env.get("CHAT_TIMEOUT_SECONDS", "60")), 1), 180)
    provider = (env.get("CHAT_PROVIDER") or "").strip().lower()
    if provider == "off":
        return None
    if provider == "groq" or (provider == "" and not env.get("OPENAI_API_KEY") and env.get("GROQ_API_KEY")):
        if not env.get("GROQ_API_KEY"):
            return None
        return OpenAIClient(env["GROQ_API_KEY"], env.get("CHAT_MODEL") or "openai/gpt-oss-120b", "https://api.groq.com/openai/v1", timeout, name="groq")
    if provider in ("", "openai") and env.get("OPENAI_API_KEY"):
        return OpenAIClient(env["OPENAI_API_KEY"], env.get("CHAT_MODEL") or "gpt-4o-mini", env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1", timeout)
    if provider == "ollama" or (provider == "" and env.get("OLLAMA_ENABLED") == "1"):
        return OllamaClient(env.get("OLLAMA_URL") or "http://127.0.0.1:11434", env.get("CHAT_MODEL") or env.get("OLLAMA_MODEL") or "qwen3:4b", timeout)
    return None
