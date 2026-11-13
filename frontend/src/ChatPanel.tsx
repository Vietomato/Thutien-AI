import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/ui";
import { Icon } from "@/icons";
import { parseMarkdown, type Inline } from "@/chatMarkdown";

type Step = { tool: string; arguments: Record<string, unknown>; ok: boolean };
type Reply = { answer: string; steps: Step[]; verified: boolean; unverified: string[] };
type Message = { role: "user" | "assistant"; content: string; reply?: Reply; failed?: boolean };

const EXAMPLES = [
  "Nếu Đại Phát trả chậm 20 ngày thì sao?",
  "Khoản nào hoãn được mà ít bị phạt nhất?",
  "Tuần nào mình thiếu tiền nhiều nhất?",
  "Khách nào có khả năng trả trễ nhất?",
];

const TOOL_LABEL: Record<string, string> = {
  get_overview: "Tổng quan", search_customers: "Tìm khách hàng", get_customer: "Hồ sơ khách hàng", list_invoices: "Danh sách hóa đơn",
  get_invoice: "Chi tiết hóa đơn", get_forecast: "Dự báo dòng tiền", get_week_detail: "Chi tiết một tuần", list_outgoings: "Khoản phải chi",
  what_if: "Thử kịch bản", defer_options: "Phương án hoãn chi", explain_method: "Cách tính",
};

const Text = ({ parts }: { parts: Inline[] }) => <>{parts.map((x, i) => x.code ? <code key={i}>{x.text}</code> : x.bold ? <strong key={i}>{x.text}</strong> : x.italic ? <em key={i}>{x.text}</em> : <span key={i}>{x.text}</span>)}</>;

function Answer({ source }: { source: string }) {
  return <div className="chat-md">{parseMarkdown(source).map((b, i) => b.kind === "p" ? <p key={i}><Text parts={b.inline} /></p>
    : b.kind === "table" ? <div className="chat-table" key={i}><table><thead><tr>{b.head.map((c, j) => <th key={j}><Text parts={c} /></th>)}</tr></thead>
      <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}><Text parts={c} /></td>)}</tr>)}</tbody></table></div>
    : b.kind === "ul" ? <ul key={i}>{b.items.map((it, j) => <li key={j}><Text parts={it} /></li>)}</ul>
    : <ol key={i}>{b.items.map((it, j) => <li key={j}><Text parts={it} /></li>)}</ol>)}</div>;
}

export function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || available !== null) return;
    api<{ available: boolean }>("/api/chat/status").then(s => setAvailable(s.available)).catch(() => setAvailable(false));
  }, [open, available]);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [messages, busy]);

  async function send(question: string) {
    question = question.trim();
    if (!question || busy) return;
    const history = messages.filter(m => !m.failed).map(m => ({ role: m.role, content: m.content }));
    setMessages(m => [...m, { role: "user", content: question }]);
    setText(""); setBusy(true);
    try {
      const reply = await api<Reply>("/api/chat", { method: "POST", body: JSON.stringify({ question, history }) });
      setMessages(m => [...m, { role: "assistant", content: reply.answer, reply }]);
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", content: errorMessage(e), failed: true }]);
    } finally { setBusy(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void send(text); };

  return <>
    <button className="chat-fab" onClick={() => setOpen(v => !v)} aria-expanded={open} aria-controls="chat-panel">
      <Icon name="sparkle" size={18} />{open ? "Đóng trợ lý" : "Hỏi trợ lý"}
    </button>
    {open && <section id="chat-panel" className="chat-panel" aria-label="Trợ lý dòng tiền">
      <header className="chat-head"><strong>Trợ lý dòng tiền</strong><span>Chỉ đọc dữ liệu, mọi con số do hệ thống tính</span></header>
      <div className="chat-body" aria-live="polite">
        {available === false && <div className="chat-note">Trợ lý chưa được cấu hình trên máy chủ (cần OPENAI_API_KEY hoặc Ollama).</div>}
        {available !== false && messages.length === 0 && <div className="chat-empty">
          <p>Hỏi về công nợ và dòng tiền, ví dụ:</p>
          {EXAMPLES.map(q => <button key={q} className="chat-chip" onClick={() => void send(q)} disabled={available === null}>{q}</button>)}
        </div>}
        {messages.map((m, i) => <div key={i} className={`chat-msg chat-${m.role}${m.failed ? " chat-failed" : ""}`}>
          {m.role === "assistant" && !m.failed ? <Answer source={m.content} /> : <p>{m.content}</p>}
          {m.reply && !m.reply.verified && <small className="chat-warn">Chưa kiểm chứng được: {m.reply.unverified.join(", ")}. Hãy đối chiếu với bảng dự báo.</small>}
          {m.reply && m.reply.steps.length > 0 && <details className="chat-how"><summary>Cách tính ({m.reply.steps.length} bước)</summary>
            <ul>{m.reply.steps.map((s, j) => <li key={j} className={s.ok ? "" : "chat-step-bad"}>{TOOL_LABEL[s.tool] ?? s.tool}{s.ok ? "" : " (lỗi, đã thử lại)"}
              <code>{JSON.stringify(s.arguments)}</code></li>)}</ul></details>}
        </div>)}
        {busy && <div className="chat-msg chat-assistant"><p className="chat-typing">Đang tính…</p></div>}
        <div ref={bottom} />
      </div>
      <form className="chat-form" onSubmit={submit}>
        <input className="input" value={text} onChange={e => setText(e.target.value)} placeholder="Nhập câu hỏi…" maxLength={2000}
          aria-label="Câu hỏi" disabled={available === false} />
        <button className="btn" disabled={busy || !text.trim() || available === false}>Gửi</button>
      </form>
    </section>}
  </>;
}
