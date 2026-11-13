import { useMemo, useState } from "react";
import { api, jsonBody } from "@/lib/api";
import { ForecastChart } from "@/forecast/ForecastChart";
import { FlightPath } from "@/FlightPath";
import { compactMoney, summarize, weekRange, type WeekRow } from "@/forecast/forecastMath";
import { confidenceOf, likelyLate, nextToPay, shortDay, summarizePrediction, timelineScale, daysBetween, type InvoiceRow, type PredictionRow } from "@/forecast/predictionMath";
import { Action, date, Head, holdName, money, Row, score, Tag } from "@/ui";

function dayDiff(asOf: string, due: string) {
  return Math.floor((Date.parse(`${asOf}T00:00:00Z`) - Date.parse(`${due}T00:00:00Z`)) / 86400000);
}

/** One invoice's payment prediction as a line: due date, today, and the range in which the customer is expected to pay. */
function PaymentTimeline({ due, asOf, prediction }: { due: string; asOf: string; prediction: Row }) {
  const p = prediction as PredictionRow;
  const s = summarizePrediction(p, due, asOf);
  const scale = timelineScale(due, asOf, p);
  const at = (iso: string) => `${(scale.at(iso) * 100).toFixed(2)}%`;
  const from = scale.at(p.predicted_date_p25), to = scale.at(p.predicted_date_p75);
  return <div className="ptl">
    <div className="ptl-track" role="img" aria-label={`Hạn trả ${shortDay(due)}, hôm nay ${shortDay(asOf)}, dự đoán trả từ ${shortDay(p.predicted_date_p25)} đến ${shortDay(p.predicted_date_p75)}`}>
      <span className="ptl-range" style={{ left: `${from * 100}%`, width: `${Math.max(to - from, 0.012) * 100}%` }} />
      <span className="ptl-mark ptl-due" style={{ left: at(due) }}><i /><em>Hạn trả {shortDay(due)}</em></span>
      <span className="ptl-mark ptl-today" style={{ left: at(asOf) }}><i /><em>Hôm nay {shortDay(asOf)}</em></span>
      <span className="ptl-mark ptl-usual" style={{ left: at(p.predicted_date_p50) }}><i /><em>Dự đoán {shortDay(p.predicted_date_p50)}</em></span>
    </div>
    <ul className="ptl-legend">
      <li><b>Sớm</b>{date(p.predicted_date_p25)}</li><li className="ptl-hi"><b>Thường lệ</b>{date(p.predicted_date_p50)}</li><li><b>Muộn</b>{date(p.predicted_date_p75)}</li>
    </ul>
    <p className="ptl-text">{s.sentence}</p>
    <p className="ptl-conf"><span className={`ptl-dot ${s.confidence.kind}`} />{s.confidence.label}</p>
  </div>;
}

/** Two short lists that put the predictions on the overview: who is about to pay, and who will probably pay after the due date. */
function PredictionLists({ items, asOf }: { items: Row[]; asOf: string }) {
  const rows = items as InvoiceRow[];
  const soon = nextToPay(rows, asOf, 3);
  const slow = likelyLate(rows, 3);
  if (!soon.length && !slow.length) return null;
  return <div className="cols pred-cols">
    <article className="card rank-card">
      <div className="card-head"><h2>Sắp được trả</h2></div>
      <p className="note">Hóa đơn có ngày trả dự đoán gần nhất, theo thói quen của từng khách.</p>
      {soon.length ? <ol className="rank">{soon.map(r => <li className="rank-row" key={r.invoice_id}>
        <span className="rank-n">{shortDay(r.prediction!.predicted_date_p50)}</span>
        <div className="rank-main"><strong>{r.display_name}</strong><span>{r.invoice_id} · {confidenceOf(r.prediction!).short}</span></div>
        <span className="rank-amt">{money(r.remaining_amount)}</span>
      </li>)}</ol> : <div className="empty">Chưa có hóa đơn nào được dự đoán trả sớm.</div>}
    </article>
    <article className="card rank-card">
      <div className="card-head"><h2>Dự kiến trả muộn</h2></div>
      <p className="note">Chưa quá hạn, nhưng khách này thường trả sau hạn. Nên nhắc trước.</p>
      {slow.length ? <ol className="rank">{slow.map(r => <li className="rank-row" key={r.invoice_id}>
        <span className="rank-n">+{daysBetween(r.due_date, r.prediction!.predicted_date_p50)} ngày</span>
        <div className="rank-main"><strong>{r.display_name}</strong><span>{r.invoice_id} · hạn {shortDay(r.due_date)}, dự đoán {shortDay(r.prediction!.predicted_date_p50)}</span></div>
        <span className="rank-amt">{money(r.remaining_amount)}</span>
      </li>)}</ol> : <div className="empty">Không có hóa đơn nào được dự đoán trả muộn.</div>}
    </article>
  </div>;
}

export function Overview({ data, onNavigate }: { data: Row; onNavigate: (page: string) => void }) {
  if (!data.summary) return <div className="empty">Chưa có dữ liệu tổng quan. Chờ đồng bộ hoàn tất hoặc bấm biểu tượng tải lại ở góc trên.</div>;
  const summary = data.summary ?? {};
  const priority: Row[] = data.priority?.items ?? [];
  const forecast = data.forecast;
  const weeks: WeekRow[] = (forecast?.weeks ?? []) as WeekRow[];
  const fs = summarize(weeks);
  const customer = data.invoices?.scope === "own";
  const figures = <section className="figs" aria-label="Công nợ hiện tại">
    <div className="fig"><span className="fig-label">Còn phải thu</span><strong className="fig-value">{money(summary.total_remaining)}</strong><span className="fig-note">{summary.open_count ?? 0} hóa đơn mở</span></div>
    <div className="fig"><span className="fig-label">Đã quá hạn</span><strong className="fig-value fig-bad">{money(summary.overdue_amount)}</strong><span className="fig-note">{summary.overdue_count ?? 0} hóa đơn</span></div>
    <div className="fig"><span className="fig-label">Đang tranh chấp</span><strong className="fig-value fig-warn">{money(summary.disputed_amount)}</strong><span className="fig-note">{summary.disputed_count ?? 0} hóa đơn</span></div>
  </section>;
  if (customer) return <>
    <Head title="Công nợ của tôi" subtitle={`Số liệu tính đến ${date(summary.as_of_date)}`} />
    {figures}
    <div className="locked"><h2>Thông tin của bạn</h2><p>Bạn chỉ xem được hóa đơn và lịch sử thanh toán của khách hàng gắn với tài khoản này.</p><button className="btn btn-ghost" onClick={() => onNavigate("invoices")}>Xem hóa đơn của tôi</button></div>
  </>;
  const worst = fs.worstIndex >= 0 ? weeks[fs.worstIndex] : null;
  return <>
    <section className="hero"><div className="hero-in">
      <div className="hero-text">
        <span className="hero-eyebrow">Kế hoạch bay 12 tuần · tính đến {date(summary.as_of_date)}</span>
        <h1 className="hero-title">{fs.weeks === 0 ? "Chưa có dữ liệu dự báo" : fs.riskyWeeks ? <>{fs.riskyWeeks} trên {fs.weeks} tuần có nguy cơ <em>thiếu tiền</em></> : <>Không có tuần nào <em>thiếu tiền</em></>}</h1>
        <p className="hero-sub">{fs.weeks === 0 ? "Khi có dự báo, hệ thống sẽ cho biết tuần nào tiền thu chưa đủ chi."
          : worst ? <>Nặng nhất là tuần {weekRange(worst.week_start)}: nếu khách trả muộn, tiền thu thấp hơn tiền phải chi khoảng {compactMoney(fs.worstGap)}.</>
          : "Kể cả khi khách trả muộn, tiền thu vẫn đủ chi trong 12 tuần tới."}</p>
        <div className="hero-actions"><button className="btn btn-light" onClick={() => onNavigate("forecast")}>Xem dự báo dòng tiền</button><button className="btn btn-line-light" onClick={() => onNavigate("invoices")}>Xem công nợ</button></div>
      </div>
      {weeks.length > 0 && <FlightPath weeks={weeks} />}
    </div></section>
    {figures}
    <div className="cols">
      <ForecastChart forecast={forecast} compact />
      <article className="card rank-card">
        <div className="card-head"><h2>Khoản cần thu trước</h2><button className="link-btn" onClick={() => onNavigate("invoices")}>Xem tất cả</button></div>
        {priority.length ? <ol className="rank">{priority.slice(0, 5).map(item => <li className="rank-row" key={item.invoice_id}>
          <span className="rank-n">{String(item.rank).padStart(2, "0")}</span>
          <div className="rank-main"><strong>{item.display_name}</strong><span>{item.invoice_id} · quá hạn {item.days_overdue} ngày</span></div>
          <span className="rank-amt">{money(item.remaining_amount)}</span>
        </li>)}</ol> : <div className="empty">Chưa có hóa đơn ưu tiên.</div>}
        <div className="note">Xếp theo: số dư còn nợ × tỷ lệ trả trễ × số ngày quá hạn.</div>
      </article>
    </div>
    <PredictionLists items={priority} asOf={String(summary.as_of_date)} />
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
    <Head title={isStaff ? "Công nợ cần thu" : "Hóa đơn của tôi"} subtitle={`${rows.length} hóa đơn còn nợ · ${isStaff ? rows.filter(x => x.eligible_for_reminder).length + " đủ điều kiện nhắc" : "dữ liệu riêng của tài khoản"} · Ngày tính toán ${date(asOf)}`} />
    <div className="toolbar"><div className="search"><input className="input" placeholder="Tìm mã hóa đơn hoặc tên khách" value={query} onChange={e => setQuery(e.target.value)} /></div><div className="filters">{([ ["all", "Tất cả"], ["overdue", "Quá hạn"], ["disputed", "Tranh chấp"], ["notdue", "Chưa đến hạn"] ] as const).map(([key, label]) => <button className="filter" key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label} ({counts[key]})</button>)}</div></div>
    <div className="table-card table-scroll"><table className="table"><thead><tr>{isStaff && <th>Ưu tiên</th>}<th>Hóa đơn</th><th>Khách hàng</th><th>Hạn trả</th><th className="num">Còn nợ</th>{isStaff && <><th>Dự đoán ngày trả</th><th>Trạng thái</th><th>Điều kiện nhắc</th></>}</tr></thead><tbody>{filtered.map(x => { const late = isStaff ? x.days_overdue : dayDiff(asOf, x.due_date); return <tr key={x.invoice_id} className={selected?.invoice_id === x.invoice_id ? "selected" : ""} onClick={() => setSelectedId(x.invoice_id)}>{isStaff && <td><strong>#{x.rank}</strong><div className="cell-sub">{score(x.priority_score)} điểm</div></td>}<td><button className="row-btn" onClick={() => setSelectedId(x.invoice_id)}>{x.invoice_id}</button></td><td>{x.display_name}<div className="cell-sub">{x.customer_id}</div></td><td>{date(x.due_date)}<div className="cell-sub">{late > 0 ? `Quá hạn ${late} ngày` : late === 0 ? "Đến hạn hôm nay" : `Còn ${-late} ngày`}</div></td><td className="num cell-strong">{money(x.remaining_amount)}</td>{isStaff && <><td>{x.prediction ? <>{date(x.prediction.predicted_date_p50)}<div className="cell-sub">{shortDay(x.prediction.predicted_date_p25)} – {shortDay(x.prediction.predicted_date_p75)}</div><div className="cell-sub">{confidenceOf(x.prediction).short}</div></> : <>Không dự đoán<div className="cell-sub">{x.dispute_status === "disputed" ? "Đang tranh chấp" : "Chưa có lịch sử"}</div></>}</td><td>{x.dispute_status === "disputed" ? <Tag kind="disp">Tranh chấp</Tag> : late > 0 ? <Tag kind="late">Quá hạn</Tag> : <Tag kind="ok">Chưa đến hạn</Tag>}</td><td>{x.eligible_for_reminder ? <Tag kind="teal">Có thể tạo nháp</Tag> : <Tag kind="ok">{(x.hold_reasons ?? []).map(holdName).join(", ") || "Chưa đủ điều kiện"}</Tag>}</td></>}</tr>; })}</tbody></table>{!filtered.length && <div className="empty">Không có hóa đơn phù hợp.</div>}</div>
    {selected && <article className="card explain"><span className="explain-label">{isStaff ? "Vì sao xếp hạng này" : "Chi tiết hóa đơn"}</span><h2>{selected.invoice_id} · {selected.display_name}</h2>{isStaff ? <><p>Điểm ưu tiên: <strong>{score(selected.priority_score)} điểm</strong> = {money(selected.remaining_amount)} × {Math.round(Number(selected.late_rate) * 100)}% tỷ lệ trả trễ ({selected.late_rate_source === "customer_history" ? "lịch sử khách" : selected.late_rate_source === "global_history" ? "lịch sử chung" : "giả định do chưa có lịch sử"}) × {selected.days_overdue} ngày quá hạn.</p><p>{selected.eligible_for_reminder ? "Đủ điều kiện tạo nháp nhắc nợ." : `Chưa đủ điều kiện nhắc: ${(selected.hold_reasons ?? []).map(holdName).join(", ")}.`}</p>{prediction ? <PaymentTimeline due={selected.due_date} asOf={asOf} prediction={prediction} /> : <p>Hóa đơn tranh chấp hoặc chưa có dự đoán.</p>}<div className="detail-actions">{canDraft && <button className="btn" disabled={!selected.eligible_for_reminder} onClick={() => void act(() => api("/api/reminders/drafts", jsonBody({ invoice_id: selected.invoice_id })), "Đã tạo nháp, chưa gửi email.").then(ok => { if (ok) onDrafts(); })}>Tạo nháp nhắc nợ</button>}<button className="btn btn-secondary" onClick={onDrafts}>Xem nháp</button>{canAssign && <button className="btn btn-secondary" onClick={onTasks}>Giao nhiệm vụ</button>}</div></> : <p>Hạn trả: {date(selected.due_date)} · Còn nợ: {money(selected.remaining_amount)}. Thông tin được đọc từ Odoo.</p>}</article>}
  </>;
}

export { ForecastPage } from "@/forecast/ForecastPage";
