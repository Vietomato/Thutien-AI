import { useMemo, useState } from "react";
import { api, jsonBody } from "@/lib/api";
import { Action, date, Head, money, Row, SourceBadge } from "@/ui";
import { ForecastChart } from "./ForecastChart";
import { compactMoney, summarize, toNumber, weekRange, type WeekRow } from "./forecastMath";
import "./forecast.css";

export function ForecastPage({ forecast, obligations, canEdit, act }: { forecast?: Row; obligations?: Row; canEdit: boolean; act: Action }) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const weeks: WeekRow[] = useMemo(() => (forecast?.weeks ?? []) as WeekRow[], [forecast]);
  const alerts: Row[] = forecast?.alerts ?? [];
  const items: Row[] = obligations?.items ?? [];
  const sources: Row = forecast?.obligations_sources ?? {};
  const beyond: Row = forecast?.receipts_out_of_horizon ?? {};
  const summary = useMemo(() => summarize(weeks), [weeks]);
  // When every receipt lands inside the 12 weeks the three scenarios add up to the same total: only the timing differs.
  const sameTotal = Math.round(summary.totalReceipts.early) === Math.round(summary.totalReceipts.late)
    && Math.round(summary.totalReceipts.usual) === Math.round(summary.totalReceipts.late);
  const hasBeyond = toNumber(beyond.p25) + toNumber(beyond.p50) + toNumber(beyond.p75) > 0 || toNumber(forecast?.obligations_out_of_horizon) > 0;
  const maxGap = Math.max(1, ...alerts.map(a => toNumber(a.gap_p75)));
  const amountValue = Number(amount);
  const valid = description.trim().length > 0 && Number.isInteger(amountValue) && amountValue > 0 && dueDate !== "";
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    const ok = await act(() => api("/api/obligations", jsonBody({ description: description.trim(), amount: amountValue, due_date: dueDate })), "Đã lưu khoản chi dự kiến.");
    if (ok) { setDescription(""); setAmount(""); setDueDate(""); }
  };

  return <>
    <Head title="Dự báo dòng tiền · F4" subtitle="Tuần nào tiền thu về có thể không đủ để chi, dựa trên thói quen trả tiền của từng khách." right={<SourceBadge source={forecast?.source} />} />

    <div className="alert alert-warning" role="note"><div>
      <div className="alert-title">Cần biết khi đọc số liệu</div>
      Ba kịch bản cho biết tiền thu có thể về sớm hay muộn, theo thói quen trả tiền trước đây của từng khách. Đây là thử sức chịu đựng, không phải cam kết,
      không phải khoảng tin cậy thống kê và không phải số dư tiền mặt (hệ thống chưa biết số dư đầu kỳ).
      Chi có hai nguồn: hóa đơn nhà cung cấp trong Odoo ({money(sources.odoo_supplier_bills)}) và khoản kế toán nhập tay ({money(sources.manual)}, {sources.manual_count ?? 0} khoản).
    </div></div>

    {weeks.length > 0 && <div className="kpis">
      <div className="kpi"><span className="kpi-label">Tuần có nguy cơ thiếu tiền</span>
        <strong className={`kpi-value ${summary.riskyWeeks ? "f4-bad" : "f4-ok"}`}>{summary.riskyWeeks}/{summary.weeks}</strong>
        <span className="kpi-note">Nếu khách trả muộn</span></div>
      <div className="kpi"><span className="kpi-label">Thiếu nhiều nhất</span>
        <strong className={`kpi-value ${summary.worstGap ? "f4-bad" : "f4-ok"}`} title={money(summary.worstGap)}>{summary.worstGap ? compactMoney(summary.worstGap) : "Không có"}</strong>
        <span className="kpi-note">{summary.worstIndex >= 0 ? `Tuần ${weekRange(weeks[summary.worstIndex].week_start)}` : "Không tuần nào thu thiếu chi"}</span></div>
      <div className="kpi"><span className="kpi-label">Thu dự kiến 12 tuần</span>
        <strong className="kpi-value" title={money(summary.totalReceipts.usual)}>{compactMoney(summary.totalReceipts.usual)}</strong>
        <span className="kpi-note">{sameTotal
          ? "Ba kịch bản cùng tổng, chỉ khác tuần tiền về"
          : `Theo thói quen. Từ ${compactMoney(summary.totalReceipts.late)} (trả muộn) đến ${compactMoney(summary.totalReceipts.early)} (trả sớm)`}</span></div>
      <div className="kpi"><span className="kpi-label">Chi dự kiến 12 tuần</span>
        <strong className="kpi-value" title={money(summary.totalObligations)}>{compactMoney(summary.totalObligations)}</strong>
        <span className="kpi-note">Odoo {compactMoney(toNumber(sources.odoo_supplier_bills))} + nhập tay {compactMoney(toNumber(sources.manual))}</span></div>
    </div>}

    <ForecastChart forecast={forecast} />

    <section className="panel">
      <div className="panel-head"><h2>Cảnh báo thu thiếu</h2><span className="note">Tuần mà tiền thu, nếu khách trả muộn, thấp hơn tiền phải chi</span></div>
      {alerts.length === 0 ? <div className="empty">Không có tuần nào thu thấp hơn chi, kể cả khi khách trả muộn.</div>
        : <div className="table-scroll"><table className="table"><thead><tr><th>Tuần</th><th className="num">Thu nếu khách trả muộn</th><th className="num">Chi dự kiến</th><th className="num">Thiếu</th></tr></thead>
          <tbody>{alerts.map(a => <tr key={a.week_start}>
            <td>{weekRange(a.week_start)}</td>
            <td className="num">{money(a.receipt_p75)}</td>
            <td className="num">{money(a.obligations)}</td>
            <td className="num"><span className="f4-gaprow"><span className="f4-gaptrack"><i className="f4-gapbar" style={{ width: `${Math.max(3, toNumber(a.gap_p75) / maxGap * 100)}%` }} /></span><strong className="f4-bad">{money(a.gap_p75)}</strong></span></td>
          </tr>)}</tbody></table></div>}
    </section>

    {hasBeyond && <div className="chart-note"><span className="note">Ngoài 12 tuần: tiền thu về sau đó (nếu trả sớm {money(beyond.p25)}, theo thói quen {money(beyond.p50)}, trả muộn {money(beyond.p75)}) và chi {money(forecast?.obligations_out_of_horizon)} chưa nằm trong biểu đồ.</span></div>}

    {canEdit && <form className="card" onSubmit={submit}><h2>Nhập khoản chi dự kiến</h2>
      <div className="note">Khoản chi bạn nhập sẽ được cộng vào hóa đơn nhà cung cấp trong Odoo khi tính dự báo.</div>
      <div className="form-grid">
        <div className="field"><label htmlFor="ob-description">Nội dung</label><input id="ob-description" className="input" value={description} onChange={e => setDescription(e.target.value)} maxLength={200} placeholder="Ví dụ: Tiền thuê văn phòng" required /></div>
        <div className="field"><label htmlFor="ob-amount">Số tiền (VND)</label><input id="ob-amount" className="input" type="number" min={1} step={1} inputMode="numeric" value={amount} onChange={e => setAmount(e.target.value)} placeholder="30000000" required /></div>
        <div className="field"><label htmlFor="ob-date">Ngày chi</label><input id="ob-date" className="input" type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} required /></div>
      </div>
      <div><button className="btn" style={{ padding: "0 18px" }} disabled={!valid}>Thêm khoản chi</button></div></form>}

    <section className="panel">
      <div className="panel-head"><h2>Khoản chi kế toán đã nhập</h2><span className="note">Nhập tay, chưa đọc từ Odoo</span></div>
      {items.length === 0 ? <div className="empty">Chưa có khoản chi nhập tay nào.</div>
        : <div className="table-scroll"><table className="table"><thead><tr><th>Ngày chi</th><th>Nội dung</th><th className="num">Số tiền</th><th>Người nhập</th></tr></thead>
          <tbody>{items.map(o => <tr key={o.id}><td>{date(o.due_date)}</td><td>{o.description}</td><td className="num">{money(o.amount)}</td><td>{o.created_by_username}</td></tr>)}</tbody></table></div>}
    </section>

    <section className="panel">
      <div className="panel-head"><h2>Số liệu từng tuần</h2><span className="note">Dữ liệu đầy đủ của biểu đồ. Hàng nền đỏ là tuần thu chưa đủ chi.</span></div>
      <div className="table-scroll"><table className="table"><thead><tr>
        <th>Tuần</th><th className="num">Thu · trả sớm</th><th className="num">Thu · theo thói quen</th><th className="num">Thu · trả muộn</th><th className="num">Chi dự kiến</th><th className="num">Thiếu (nếu trả muộn)</th>
      </tr></thead><tbody>{weeks.map(w => <tr key={w.week_start} className={w.gap_p75 > 0 ? "f4-row-short" : ""}>
        <td>{weekRange(w.week_start)}</td><td className="num">{money(w.receipt_p25)}</td><td className="num">{money(w.receipt_p50)}</td>
        <td className="num">{money(w.receipt_p75)}</td><td className="num">{money(w.obligations)}</td><td className="num">{money(w.gap_p75)}</td>
      </tr>)}</tbody></table></div>
    </section>
  </>;
}
