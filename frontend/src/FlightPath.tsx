import { compactMoney, shortDate, toNumber, type WeekRow } from "@/forecast/forecastMath";
import "./flightpath.css";

/**
 * The CashPilot signature picture: twelve weeks as waypoints on a flight route.
 * Height above the ground line = receipts (if customers pay late) minus outgoings that week.
 * Waypoints that sink below the line are weeks where receipts do not cover outgoings; the worst one is labelled.
 */
export function FlightPath({ weeks }: { weeks: WeekRow[] }) {
  const n = weeks.length;
  if (!n) return null;
  const W = 620, H = 340, padX = 38, ground = 190, amp = 118;
  const nets = weeks.map(w => toNumber(w.receipt_p75) - toNumber(w.obligations));
  const maxAbs = Math.max(1, ...nets.map(Math.abs));
  const pts = nets.map((v, i) => ({ x: padX + (n === 1 ? 0 : (i * (W - 2 * padX)) / (n - 1)), y: ground - (v / maxAbs) * amp, short: v < 0, v, w: weeks[i] }));
  const route = pts.map((p, i) => {
    if (i === 0) return `M${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    const p0 = pts[i - 2] ?? pts[i - 1], p1 = pts[i - 1], p3 = pts[i + 1] ?? p;
    const c1x = p1.x + (p.x - p0.x) / 6, c1y = p1.y + (p.y - p0.y) / 6, c2x = p.x - (p3.x - p1.x) / 6, c2y = p.y - (p3.y - p1.y) / 6;
    return `C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(" ");
  const worst = pts.reduce((a, b) => (b.v < a.v ? b : a), pts[0]);
  const angle = n > 1 ? (Math.atan2(pts[1].y - pts[0].y, pts[1].x - pts[0].x) * 180) / Math.PI : 0;
  const shortCount = pts.filter(p => p.short).length;
  return <figure className="fp">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Kế hoạch bay 12 tuần: ${shortCount} tuần thu chưa đủ chi`}>
      {[0, 1, 2, 3, 4, 5].map(i => <line key={`h${i}`} className="fp-grid" x1="0" x2={W} y1={30 + i * 56} y2={30 + i * 56} />)}
      {Array.from({ length: 13 }, (_, i) => <line key={`v${i}`} className="fp-grid" y1="30" y2={H - 40} x1={padX + (i * (W - 2 * padX)) / 12} x2={padX + (i * (W - 2 * padX)) / 12} />)}
      <line className="fp-ground" x1="0" x2={W} y1={ground} y2={ground} />
      <text className="fp-axis" x="8" y={ground - 8}>Thu vượt chi</text>
      <text className="fp-axis" x="8" y={ground + 16}>Thu thiếu chi</text>
      {pts.map((p, i) => <line key={`d${i}`} className={`fp-drop${p.short ? " is-short" : ""}`} x1={p.x} x2={p.x} y1={p.y} y2={ground} />)}
      <path className="fp-route" d={route} pathLength={1} />
      {pts.map((p, i) => <g key={i} className="fp-wp" style={{ animationDelay: `${0.25 + i * 0.12}s` }}>
        <circle className={`fp-node${p.short ? " is-short" : ""}`} cx={p.x} cy={p.y} r={p.short ? 6 : 4.5} />
        {p.short && <circle className="fp-halo" cx={p.x} cy={p.y} r="11" />}
        <text className="fp-date" x={p.x} y={H - 14} textAnchor="middle">{shortDate(p.w.week_start)}</text>
      </g>)}
      {worst.short && <g className="fp-flag" transform={`translate(${Math.min(Math.max(worst.x, 70), W - 70)}, ${Math.min(worst.y + 30, H - 62)})`}>
        <rect x="-62" y="-14" width="124" height="26" rx="13" />
        <text textAnchor="middle" y="4">−{compactMoney(Math.abs(worst.v))}</text>
      </g>}
      <g className="fp-plane" transform={`translate(${pts[0].x} ${pts[0].y}) rotate(${angle}) scale(1.5)`}><path d="M-9 -8 L15 0 L-9 8 L-4 0 Z" /></g>
    </svg>
    <figcaption>Mỗi điểm là một tuần. Điểm đỏ: thu chưa đủ chi nếu khách trả muộn.</figcaption>
  </figure>;
}
