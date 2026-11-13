import { useEffect, useId, useMemo, useRef, useState } from "react";
import { money, Row } from "@/ui";
import {
  LATE, SCENARIOS, compactMoney, defaultWeek, gapOf, hasAnyMoney, niceScale, receiptOf, shortDate, summarize,
  toNumber, weekRange, type ScenarioKey, type WeekRow,
} from "./forecastMath";
import "./forecast.css";


/** Width of an element in px, kept up to date, so the chart can be drawn at its real size (text never gets scaled down). */
function useWidth<T extends HTMLElement>(active: boolean) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!active || !el) return;
    const update = () => setWidth(Math.round(el.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [active]);
  return [ref, width] as const;
}

/** The invoices that make up one week's expected receipts: amount x the probability the customer pays that week. */
function Contributors({ week }: { week?: Row }) {
  if (!week) return null;
  const items: Row[] = week.items ?? [];
  if (!items.length) return <p className="f4-note">Tuần này chưa có hóa đơn nào được kỳ vọng thu.</p>;
  return <section className="f4-contrib" aria-label="Hóa đơn kỳ vọng thu trong tuần đang chọn">
    <h3>Hóa đơn kỳ vọng thu trong tuần này</h3>
    <p className="f4-note">Đây là các hóa đơn tạo nên số ở cột “theo thói quen”: số tiền còn nợ × xác suất khách trả trong tuần này, rút ra từ lịch sử trả của từng khách.</p>
    <ul>{items.map(r => <li key={r.invoice_id}>
      <div><strong>{r.display_name}</strong><small>{r.invoice_id} · còn nợ {compactMoney(toNumber(r.remaining_amount))}</small></div>
      <span className="f4-prob" title="Xác suất trả trong tuần này">{Math.round(toNumber(r.probability) * 100)}%</span>
      <b title={money(r.expected_amount)}>{compactMoney(toNumber(r.expected_amount))}</b>
    </li>)}</ul>
    {toNumber(week.more_count) > 0 && <p className="f4-more">và {week.more_count} hóa đơn khác, tổng kỳ vọng {compactMoney(toNumber(week.more_amount))}</p>}
  </section>;
}

/**
 * Money coming in against money going out, week by week.
 * One scenario is drawn at a time (default: customers pay late, the scenario the warnings use), so the picture never
 * mixes three overlapping lines. A week whose receipts do not cover the outgoings gets a red column and its shortfall.
 * Hover, tap or use the arrow keys on a week to read its exact figures below the chart.
 */
export function ForecastChart({ forecast, compact = false, initialScenario = "late", initialWeek = null }:
  { forecast?: Row; compact?: boolean; initialScenario?: ScenarioKey; initialWeek?: number | null }) {
  const weeks: WeekRow[] = useMemo(() => (forecast?.weeks ?? []) as WeekRow[], [forecast]);
  const [scenarioKey, setScenarioKey] = useState<ScenarioKey>(initialScenario);
  const [picked, setPicked] = useState<number | null>(initialWeek);
  const titleId = useId();
  const scenario = compact ? LATE : SCENARIOS.find(s => s.key === scenarioKey) ?? LATE;
  const summary = useMemo(() => summarize(weeks), [weeks]);
  const cardStyle = compact ? { flex: "2 1 640px" } : undefined;
  const hasData = weeks.length > 0 && hasAnyMoney(weeks);
  const [scrollRef, width] = useWidth<HTMLDivElement>(hasData);

  if (!hasData) {
    return <article className="card f4-card" style={cardStyle}>
      <h2>Thu và chi từng tuần</h2>
      <div className="empty">{weeks.length ? "Chưa có khoản thu hay chi nào trong 12 tuần tới." : "Chưa có dữ liệu dự báo từ API."}</div>
    </article>;
  }

  const active = Math.min(picked ?? defaultWeek(weeks, scenario), weeks.length - 1);
  const anyShort = weeks.some(w => gapOf(w, scenario) > 0);
  const minW = compact ? 560 : 720;                        // below this the chart scrolls sideways instead of shrinking its text
  const W = Math.max(width || (compact ? 720 : 960), minW);
  const needsScroll = width > 0 && width < minW;
  const H = compact ? 270 : 380;
  const m = { l: 68, r: 14, t: compact ? 20 : 36, b: 54 };
  const plotW = W - m.l - m.r;
  const plotH = H - m.t - m.b;
  // One scale for every scenario, so switching scenario changes the bars but never the axis.
  const maxValue = Math.max(0, ...weeks.flatMap(w => [w.receipt_p25, w.receipt_p50, w.receipt_p75, w.receipt_expected, w.obligations].map(toNumber)));
  const scale = niceScale(maxValue);
  const y = (v: number) => m.t + plotH - (Math.max(v, 0) / scale.top) * plotH;
  const slot = plotW / weeks.length;
  const barW = Math.min(30, slot * 0.3);
  const current = weeks[active];
  const currentGap = gapOf(current, scenario);

  const onKey = (e: React.KeyboardEvent<SVGGElement>, i: number) => {
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? weeks.length - 1 : null;
    if (next === null || next < 0 || next >= weeks.length) return;
    e.preventDefault();
    (e.currentTarget.parentElement?.querySelector(`[data-week="${next}"]`) as SVGGElement | null)?.focus();
  };

  return <article className="card f4-card" style={cardStyle}>
    <header className="f4-head">
      <div>
        <h2 id={titleId}>Thu và chi từng tuần</h2>
        <p className="f4-sub">Mỗi tuần có hai cột: tiền dự kiến <strong>thu về</strong> và tiền <strong>phải chi</strong>. Nền đỏ là tuần thu chưa đủ chi.</p>
      </div>
      {!compact && <div className="f4-seg" role="group" aria-label="Kịch bản thu tiền">
        {SCENARIOS.map(s => <button key={s.key} type="button" aria-pressed={s.key === scenario.key}
          onClick={() => setScenarioKey(s.key)}>
          <span>{s.label}</span><small>{s.statistic}{s.key === "late" ? " · dùng để cảnh báo" : ""}</small>
        </button>)}
      </div>}
    </header>
    {!compact && <p className="f4-hint"><strong>{scenario.label}.</strong> {scenario.hint}</p>}

    <ul className="f4-legend" aria-label="Chú thích">
      <li><i className="f4-key f4-key-in" />Tiền thu dự kiến{compact ? " (khách trả muộn)" : ""}</li>
      <li><i className="f4-key f4-key-out" />Tiền chi dự kiến</li>
      {anyShort && <li><i className="f4-key f4-key-short" />Tuần thu chưa đủ chi</li>}
    </ul>

    {needsScroll && <p className="f4-swipe">Vuốt ngang để xem đủ 12 tuần.</p>}
    <div className="f4-scroll" ref={scrollRef}>
      <svg className="f4-svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="group" aria-labelledby={titleId} focusable="false">
        {scale.ticks.map(t => <g key={t}>
          <line className={t === 0 ? "f4-axis" : "f4-grid"} x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} />
          <text className="f4-ylabel" x={m.l - 10} y={y(t)} dy="0.32em" textAnchor="end">{compactMoney(t)}</text>
        </g>)}

        {weeks.map((w, i) => {
          const x0 = m.l + slot * i;
          const cx = x0 + slot / 2;
          const receipt = receiptOf(w, scenario);
          const out = toNumber(w.obligations);
          const gap = gapOf(w, scenario);
          const label = `Tuần ${weekRange(w.week_start)}: thu ${money(receipt)}, chi ${money(out)}, ${gap > 0 ? `thiếu ${money(gap)}` : "thu đủ chi"}`;
          return <g key={w.week_start} data-week={i} tabIndex={0} role="button" aria-pressed={i === active} aria-label={label}
            className={`f4-week${gap > 0 ? " is-short" : ""}${i === active ? " is-active" : ""}`}
            onMouseEnter={() => setPicked(i)} onFocus={() => setPicked(i)} onClick={() => setPicked(i)} onKeyDown={e => onKey(e, i)}>
            <rect className="f4-col" x={x0 + 2} y={m.t} width={slot - 4} height={plotH} rx={6} />
            <rect className="f4-in" x={cx - barW - 2} y={y(receipt)} width={barW} height={Math.max(y(0) - y(receipt), 0)} rx={3} />
            <rect className="f4-out" x={cx + 2} y={y(out)} width={barW} height={Math.max(y(0) - y(out), 0)} rx={3} />
            {gap > 0 && !compact && <text className="f4-gaplabel" x={cx} y={m.t - 12} textAnchor="middle">−{compactMoney(gap)}</text>}
            <text className="f4-xdate" x={cx} y={H - m.b + 20} textAnchor="middle">{shortDate(w.week_start)}</text>
            <text className="f4-xweek" x={cx} y={H - m.b + 36} textAnchor="middle">Tuần {i + 1}</text>
          </g>;
        })}
      </svg>
    </div>

    {compact
      ? <p className="f4-summary">{summary.riskyWeeks
          ? <><strong className="f4-bad">{summary.riskyWeeks} tuần</strong> có nguy cơ thiếu tiền nếu khách trả muộn. Thiếu nhiều nhất <strong>{compactMoney(summary.worstGap)}</strong> (tuần {weekRange(weeks[summary.worstIndex].week_start)}). Xem chi tiết ở mục Dự báo dòng tiền.</>
          : <>Không có tuần nào thiếu tiền, kể cả khi khách trả muộn.</>}</p>
      : <section className="f4-detail" aria-live="polite" aria-label="Chi tiết tuần đang chọn">
          <div className="f4-detail-head">
            <strong>Tuần {weekRange(current.week_start)}</strong>
            <span className={`f4-status ${currentGap > 0 ? "bad" : "ok"}`}>{currentGap > 0 ? `Thiếu ${compactMoney(currentGap)}` : "Thu đủ chi"}</span>
          </div>
          <dl className="f4-detail-grid">
            {SCENARIOS.map(s => <div key={s.key} className={s.key === scenario.key ? "is-current" : ""}>
              <dt>Thu · {s.label.toLowerCase()}</dt><dd title={money(receiptOf(current, s))}>{compactMoney(receiptOf(current, s))}</dd>
            </div>)}
            <div><dt>Chi dự kiến</dt><dd title={money(current.obligations)}>{compactMoney(toNumber(current.obligations))}</dd></div>
          </dl>
          <p className="f4-note">Thiếu = chi trừ thu, theo kịch bản “{scenario.label.toLowerCase()}”. Đây không phải số dư tiền mặt vì hệ thống chưa biết số dư đầu kỳ.</p>
        </section>}
    {!compact && <Contributors week={(forecast?.week_invoices as Row[] | undefined)?.[active]} />}
  </article>;
}
