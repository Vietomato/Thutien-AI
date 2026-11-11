import { useMemo, useState } from "react";
import { api, jsonBody } from "@/lib/api";
import { Action, date, Head, holdName, methodName, money, Row, score, Tag } from "@/ui";

function SourceBadge({ source }: { source?: string }) {
  const label = source === "odoo_online" ? "Odoo.com" : source === "odoo" ? "Odoo local" : "Odoo";
  return <span className="pill pill-success"><span className="pill-dot" />Nguồn: {label} (chỉ đọc)</span>;
}

function dayDiff(asOf: string, due: string) {
  return Math.floor((Date.parse(`${asOf}T00:00:00Z`) - Date.parse(`${due}T00:00:00Z`)) / 86400000);
}

export function ForecastChart({ forecast }: { forecast?: Row }) {
  const weeks: Row[] = forecast?.weeks ?? [];
  const max = Math.max(1, ...weeks.flatMap(w => [w.receipt_p75, w.obligations]));
  const height = (n: number) => `${Math.max(1, Math.min(100, Number(n) / max * 100))}%`;
  return <article className="card" style={{ flex: "2 1 640px" }}>
    <div className="chart-head"><h2>Dòng tiền dự báo · 12 tuần</h2><div className="legend"><span><i className="sw sw-band" />P25–P75</span><span><i className="sw sw-p50" />P50</span><span><i className="sw sw-obl" />Nghĩa vụ</span></div></div>
    <div className="chart-scroll"><div className="chart">{weeks.map((w, i) => <div className="wk" key={w.week_start} title={`Tuần ${i + 1}: P25 ${money(w.receipt_p25)}, P50 ${money(w.receipt_p50)}, P75 ${money(w.receipt_p75)}, nghĩa vụ ${money(w.obligations)}`}>
      <div className="wk-plot"><div className="wk-band" style={{ bottom: height(w.receipt_p25), height: `${Math.max(2, (Number(w.receipt_p75) - Number(w.receipt_p25)) / max * 100)}%` }} /><div className="wk-bar" style={{ height: height(w.receipt_p50) }} /><div className="wk-obl" style={{ bottom: height(w.obligations) }} /></div>
      <span className="wk-date">{date(w.week_start).slice(0, 5)}</span><span className="wk-gap">{w.gap_p75 > 0 ? "!" : ""}</span>
    </div>)}</div></div>
    {!weeks.length && <div className="empty">Chưa có dữ liệu dự báo từ API.</div>}
    <div className="chart-note"><span className="note">Thu: hóa đơn Odoo. Chi: hóa đơn nhà cung cấp Odoo cộng khoản kế toán nhập tay. Các phân vị do backend tính.</span><span className="note">P25 = thu sớm, P50 = trung vị, P75 = thu muộn.</span></div>
  </article>;
}

export function Overview({ data, onNavigate }: { data: Row; onNavigate: (page: string) => void }) {
  if (!data.summary) return <div className="empty">Chưa có dữ liệu tổng quan. Chờ đồng bộ hoàn tất hoặc bấm “Tải lại dữ liệu” ở cuối trang.</div>;
  const summary = data.summary ?? {};
  const priority: Row[] = data.priority?.items ?? [];
  const forecast = data.forecast;
  const risky = forecast?.risky_weeks ?? 0;
  const customer = data.invoices?.scope === "own";
  return <>
    <Head title={customer ? "Công nợ của tôi" : "Tổng quan"} subtitle={`Ngày tính toán ${date(summary.as_of_date)} · Dữ liệu đọc từ Odoo`} right={<SourceBadge source={summary.source} />} />
    <div className={`kpis ${customer ? "kpis-3" : ""}`}>
      <div className="kpi"><span className="kpi-label">Còn phải thu</span><strong className="kpi-value">{money(summary.total_remaining)}</strong><span className="kpi-note">{summary.open_count ?? 0} hóa đơn mở</span></div>
      <div className="kpi"><span className="kpi-label">Đã quá hạn</span><strong className="kpi-value c-danger">{money(summary.overdue_amount)}</strong><span className="kpi-note">{summary.overdue_count ?? 0} hóa đơn</span></div>
      <div className="kpi"><span className="kpi-label">Đang tranh chấp</span><strong className="kpi-value c-warning">{money(summary.disputed_amount)}</strong><span className="kpi-note">{summary.disputed_count ?? 0} hóa đơn</span></div>
      {!customer && <div className="kpi"><span className="kpi-label">Tuần có nguy cơ thiếu tiền</span><strong className="kpi-value c-teal">{risky}</strong><span className="kpi-note">Trong 12 tuần dự báo</span></div>}
    </div>
    {customer ? <div className="locked"><h2>Thông tin của bạn</h2><p>Bạn chỉ xem được hóa đơn và lịch sử thanh toán của khách hàng gắn với tài khoản này.</p><button className="btn btn-ghost" onClick={() => onNavigate("invoices")}>Xem hóa đơn của tôi</button></div> : <div className="cols">
      <ForecastChart forecast={forecast} />
      <article className="card" style={{ flex: "1 1 300px" }}><h2>Ưu tiên thu nợ F3</h2><div className="note">Điểm = số dư còn nợ × tỷ lệ trả trễ × số ngày quá hạn.</div>{priority.slice(0, 4).map(item => <div className="prio" key={item.invoice_id}><div className="prio-top"><span className="prio-who">#{item.rank} {item.display_name}</span><span className="prio-amt">{money(item.remaining_amount)}</span></div><div className="prio-meta"><span>{item.invoice_id} · quá hạn {item.days_overdue} ngày</span><span className="prio-tag">{score(item.priority_score)} điểm</span></div><div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(2, Number(item.priority_score) / Math.max(1, Number(priority[0]?.priority_score)) * 100)}%` }} /></div></div>)}{!priority.length && <div className="empty">Chưa có hóa đơn ưu tiên.</div>}<button className="btn btn-secondary" onClick={() => onNavigate("invoices")}>Xem toàn bộ công nợ</button></article>
    </div>}
    {!customer && <div className={`risk ${risky ? "" : "risk-ok"}`}><span className="risk-dot" /><span>{risky ? `${risky} tuần có nghĩa vụ lớn hơn khoản thu P75. Xem biểu đồ để kiểm tra từng tuần.` : "Chưa thấy tuần có nghĩa vụ vượt khoản thu P75 trong dữ liệu hiện tại."}</span></div>}
  </>;
}

export function Invoices({ data, isStaff, canDraft, canAssign, onDrafts, onTasks, act }: { data: Row; isStaff: boolean; canDraft: boolean; canAssign: boolean; onDrafts: () => void; onTasks: () => void; act: Action }) {
  const priority: Row[] = data.priority?.items ?? [];
  const plain: Row[] = data.invoices?.items ?? [];
  const rows = isStaff ? priority : plain;
  const asOf = data.priority?.as_of_date ?? data.invoices?.as_of_date ?? "";
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const selected = rows.find(x => x.invoice_id === selectedId) ?? rows[0];
  const filtered = useMemo(() => rows.filter(x => {
    const days = isStaff ? x.days_overdue : dayDiff(asOf, x.due_date);
    const pass = filter === "all" || (filter === "overdue" && days > 0) || (filter === "disputed" && x.dispute_status === "disputed") || (filter === "notdue" && days <= 0);
    return pass && `${x.invoice_id} ${x.display_name} ${x.customer_id}`.toLowerCase().includes(query.toLowerCase());
  }), [rows, asOf, filter, query, isStaff]);
  const counts = { all: rows.length, overdue: rows.filter(x => (isStaff ? x.days_overdue : dayDiff(asOf, x.due_date)) > 0).length, disputed: rows.filter(x => x.dispute_status === "disputed").length, notdue: rows.filter(x => (isStaff ? x.days_overdue : dayDiff(asOf, x.due_date)) <= 0).length };
  const prediction = selected?.prediction;
  return <>
    <Head title={isStaff ? "Công nợ · Ưu tiên F3" : "Hóa đơn của tôi"} subtitle={`${rows.length} hóa đơn còn nợ · ${isStaff ? rows.filter(x => x.eligible_for_reminder).length + " đủ điều kiện nhắc" : "dữ liệu riêng của tài khoản"} · Ngày tính toán ${date(asOf)}`} right={<SourceBadge source={data.invoices?.source ?? data.priority?.source} />} />
    <div className="toolbar"><div className="search"><input className="input" placeholder="Tìm mã hóa đơn hoặc tên khách" value={query} onChange={e => setQuery(e.target.value)} /></div><div className="filters">{([ ["all", "Tất cả"], ["overdue", "Quá hạn"], ["disputed", "Tranh chấp"], ["notdue", "Chưa đến hạn"] ] as const).map(([key, label]) => <button className="filter" key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label} ({counts[key]})</button>)}</div></div>
    <div className="table-card table-scroll"><table className="table"><thead><tr>{isStaff && <th>Ưu tiên</th>}<th>Hóa đơn</th><th>Khách hàng</th><th>Hạn trả</th><th className="num">Còn nợ</th>{isStaff && <><th>Dự đoán trả</th><th>Trạng thái</th><th>Điều kiện nhắc</th></>}</tr></thead><tbody>{filtered.map(x => { const late = isStaff ? x.days_overdue : dayDiff(asOf, x.due_date); return <tr key={x.invoice_id} className={selected?.invoice_id === x.invoice_id ? "selected" : ""} onClick={() => setSelectedId(x.invoice_id)}>{isStaff && <td><strong>#{x.rank}</strong><div className="cell-sub">{score(x.priority_score)} điểm</div></td>}<td><button className="row-btn" onClick={() => setSelectedId(x.invoice_id)}>{x.invoice_id}</button></td><td>{x.display_name}<div className="cell-sub">{x.customer_id}</div></td><td>{date(x.due_date)}<div className="cell-sub">{late > 0 ? `Quá hạn ${late} ngày` : late === 0 ? "Đến hạn hôm nay" : `Còn ${-late} ngày`}</div></td><td className="num cell-strong">{money(x.remaining_amount)}</td>{isStaff && <><td>{x.prediction ? date(x.prediction.predicted_date_p50) : "Không dự đoán"}<div className="cell-sub">{x.prediction && methodName(x.prediction.method)}</div></td><td>{x.dispute_status === "disputed" ? <Tag kind="disp">Tranh chấp</Tag> : late > 0 ? <Tag kind="late">Quá hạn</Tag> : <Tag kind="ok">Chưa đến hạn</Tag>}</td><td>{x.eligible_for_reminder ? <Tag kind="teal">Có thể tạo nháp</Tag> : <Tag kind="ok">{(x.hold_reasons ?? []).map(holdName).join(", ") || "Chưa đủ điều kiện"}</Tag>}</td></>}</tr>; })}</tbody></table>{!filtered.length && <div className="empty">Không có hóa đơn phù hợp.</div>}</div>
    {selected && <article className="card explain"><span className="explain-label">{isStaff ? "Vì sao xếp hạng này" : "Chi tiết hóa đơn"}</span><h2>{selected.invoice_id} · {selected.display_name}</h2>{isStaff ? <><p>Ưu tiên F3: <strong>{score(selected.priority_score)} điểm</strong> = {money(selected.remaining_amount)} × {Math.round(Number(selected.late_rate) * 100)}% tỷ lệ trả trễ ({selected.late_rate_source === "customer_history" ? "lịch sử khách" : selected.late_rate_source === "global_history" ? "lịch sử chung" : "giả định do chưa có lịch sử"}) × {selected.days_overdue} ngày quá hạn.</p><p>{selected.eligible_for_reminder ? "Đủ điều kiện tạo nháp nhắc nợ." : `Chưa đủ điều kiện nhắc: ${(selected.hold_reasons ?? []).map(holdName).join(", ")}.`}</p>{prediction ? <><p>{prediction.history_count ? `Dựa trên ${prediction.history_count} hóa đơn đã thanh toán. ` : "Chưa có lịch sử thanh toán. "}{prediction.overdue_adjusted && "Ngày dự đoán được điều chỉnh vì hóa đơn đã quá hạn lâu hơn các lần trả trước."}</p><div className="stat3">{(["p25", "p50", "p75"] as const).map(p => <div className={`stat ${p === "p50" ? "stat-hi" : ""}`} key={p}><div className="stat-k">{p.toUpperCase()}</div><div className="stat-v">{date(prediction[`predicted_date_${p}`])}</div><div className="micro">{methodName(prediction.method)}</div></div>)}</div></> : <p>Hóa đơn tranh chấp hoặc chưa có dự đoán.</p>}<div className="detail-actions">{canDraft && <button className="btn" disabled={!selected.eligible_for_reminder} onClick={() => void act(() => api("/api/reminders/drafts", jsonBody({ invoice_id: selected.invoice_id })), "Đã tạo nháp, chưa gửi email.").then(ok => { if (ok) onDrafts(); })}>Tạo nháp nhắc nợ</button>}<button className="btn btn-secondary" onClick={onDrafts}>Xem nháp</button>{canAssign && <button className="btn btn-secondary" onClick={onTasks}>Giao nhiệm vụ</button>}</div></> : <p>Hạn trả: {date(selected.due_date)} · Còn nợ: {money(selected.remaining_amount)}. Thông tin được đọc từ Odoo.</p>}</article>}
  </>;
}

export function ForecastPage({ forecast, obligations, canEdit, act }: { forecast?: Row; obligations?: Row; canEdit: boolean; act: Action }) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const alerts: Row[] = forecast?.alerts ?? [];
  const items: Row[] = obligations?.items ?? [];
  const sources: Row = forecast?.obligations_sources ?? {};
  const beyond: Row = forecast?.receipts_out_of_horizon ?? {};
  const hasBeyond = Number(beyond.p25 ?? 0) + Number(beyond.p50 ?? 0) + Number(beyond.p75 ?? 0) > 0 || Number(forecast?.obligations_out_of_horizon ?? 0) > 0;
  const amountValue = Number(amount);
  const valid = description.trim().length > 0 && Number.isInteger(amountValue) && amountValue > 0 && dueDate !== "";
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    const payload = { description: description.trim(), amount: amountValue, due_date: dueDate };
    const ok = await act(() => editingId === null
      ? api("/api/obligations", jsonBody(payload))
      : api(`/api/obligations/${editingId}`, { method: "PATCH", body: JSON.stringify(payload) }),
    editingId === null ? "Đã lưu khoản chi dự kiến." : "Đã cập nhật khoản chi.");
    if (ok) { setDescription(""); setAmount(""); setDueDate(""); setEditingId(null); }
  };
  const startEdit = (item: Row) => {
    setEditingId(Number(item.id)); setDescription(String(item.description));
    setAmount(String(item.amount)); setDueDate(String(item.due_date));
    document.getElementById("ob-description")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const remove = (item: Row) => {
    if (!window.confirm(`Xóa khoản chi “${item.description}” khỏi dự báo?`)) return;
    void act(() => api(`/api/obligations/${item.id}`, { method: "DELETE" }), "Đã xóa khoản chi khỏi dự báo.");
  };
  return <>
    <Head title="Dự báo dòng tiền · F4" subtitle="Phân vị ngày trả được tính từ lịch sử thanh toán. Chi gồm hóa đơn nhà cung cấp trong Odoo và khoản kế toán nhập tay." right={<SourceBadge source={forecast?.source} />} />
    <div className="alert alert-warning" role="note"><div><div className="alert-title">Cần biết khi đọc số liệu</div>Ba đường là kịch bản thử sức chịu đựng (tiền về sớm, giữa, muộn), không phải khoảng tin cậy thống kê và không phản ánh số dư tiền mặt. Chi có hai nguồn: hóa đơn nhà cung cấp trong Odoo ({money(sources.odoo_supplier_bills)}) và khoản chi kế toán nhập tay ({money(sources.manual)}, {sources.manual_count ?? 0} khoản).</div></div>
    <ForecastChart forecast={forecast} />
    <section className="panel">
      <div className="panel-head"><h2>Cảnh báo thu thiếu</h2><span className="note">Tuần mà thu ở kịch bản bi quan (P75) thấp hơn chi</span></div>
      {alerts.length === 0 ? <div className="empty">Không có tuần nào thu thấp hơn chi ở kịch bản bi quan.</div>
        : <div className="table-scroll"><table className="table"><thead><tr><th>Tuần bắt đầu</th><th className="num">Thu bi quan (P75)</th><th className="num">Chi</th><th className="num">Thiếu</th></tr></thead>
          <tbody>{alerts.map(a => <tr key={a.week_start}><td>{date(a.week_start)}</td><td className="num">{money(a.receipt_p75)}</td><td className="num">{money(a.obligations)}</td><td className="num">{money(a.gap_p75)}</td></tr>)}</tbody></table></div>}
    </section>
    {hasBeyond && <div className="chart-note"><span className="note">Ngoài 12 tuần: thu P25 {money(beyond.p25)}, P50 {money(beyond.p50)}, P75 {money(beyond.p75)}; chi {money(forecast?.obligations_out_of_horizon)}. Các khoản này không nằm trong biểu đồ.</span></div>}
    {canEdit && <form className="card" onSubmit={submit}><h2>{editingId === null ? "Nhập khoản chi dự kiến" : "Sửa khoản chi dự kiến"}</h2>
      <div className="form-grid">
        <div className="field"><label htmlFor="ob-description">Nội dung</label><input id="ob-description" className="input" value={description} onChange={e => setDescription(e.target.value)} maxLength={200} placeholder="Ví dụ: Tiền thuê văn phòng" required /></div>
        <div className="field"><label htmlFor="ob-amount">Số tiền (VND)</label><input id="ob-amount" className="input" type="number" min={1} step={1} inputMode="numeric" value={amount} onChange={e => setAmount(e.target.value)} placeholder="30000000" required /></div>
        <div className="field"><label htmlFor="ob-date">Ngày chi</label><input id="ob-date" className="input" type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} required /></div>
      </div>
      <div className="form-actions"><button className="btn" style={{ padding: "0 18px" }} disabled={!valid}>{editingId === null ? "Thêm khoản chi" : "Lưu thay đổi"}</button>{editingId !== null && <button className="btn btn-secondary" type="button" onClick={() => { setEditingId(null); setDescription(""); setAmount(""); setDueDate(""); }}>Hủy sửa</button>}</div></form>}
    <section className="panel">
      <div className="panel-head"><h2>Khoản chi kế toán đã nhập</h2><span className="note">Nhập tay, chưa đọc từ Odoo</span></div>
      {items.length === 0 ? <div className="empty">Chưa có khoản chi nhập tay nào.</div>
        : <div className="table-scroll"><table className="table"><thead><tr><th>Ngày chi</th><th>Nội dung</th><th className="num">Số tiền</th><th>Người nhập</th>{canEdit && <th>Thao tác</th>}</tr></thead>
          <tbody>{items.map(o => <tr key={o.id}><td>{date(o.due_date)}</td><td>{o.description}</td><td className="num">{money(o.amount)}</td><td>{o.created_by_username}</td>{canEdit && <td><div className="form-actions"><button className="btn btn-secondary btn-compact" type="button" onClick={() => startEdit(o)}>Sửa</button><button className="btn btn-secondary btn-compact" type="button" onClick={() => remove(o)}>Xóa</button></div></td>}</tr>)}</tbody></table></div>}
    </section>
    <div className="table-card table-scroll"><table className="table"><thead><tr><th>Tuần</th><th className="num">P25</th><th className="num">P50</th><th className="num">P75</th><th className="num">Chi</th><th className="num">Thiếu theo P75</th></tr></thead><tbody>{(forecast?.weeks ?? []).map((w: Row) => <tr key={w.week_start}><td>{date(w.week_start)}</td><td className="num">{money(w.receipt_p25)}</td><td className="num">{money(w.receipt_p50)}</td><td className="num">{money(w.receipt_p75)}</td><td className="num">{money(w.obligations)}</td><td className="num">{money(w.gap_p75)}</td></tr>)}</tbody></table></div>
  </>;
}
