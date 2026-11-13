// Pure helpers that make a payment prediction readable: no React, no network (npm test).
// A prediction is three dates for one open invoice: early (P25), usual (P50) and late (P75), plus how it was obtained.

export type PredictionRow = {
  predicted_date_p25: string;
  predicted_date_p50: string;
  predicted_date_p75: string;
  history_count?: number;
  method?: string;
  low_history?: boolean;
  overdue_adjusted?: boolean;
};

export type InvoiceRow = {
  invoice_id: string;
  display_name: string;
  remaining_amount: number | string;
  due_date: string;
  days_overdue: number;
  prediction?: PredictionRow | null;
};

/** Calendar day number of an ISO date (UTC, so time zones never shift a day). */
export const dayNumber = (iso: string): number => Math.floor(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / 86400000);

/** Days from `fromIso` to `toIso` (negative when `toIso` is earlier). */
export const daysBetween = (fromIso: string, toIso: string): number => dayNumber(toIso) - dayNumber(fromIso);

/** "2026-11-22" -> "22/11". */
export const shortDay = (iso: string): string => {
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}`;
};

export type Confidence = { kind: "own" | "shared" | "none"; label: string; short: string };

/** How much history stands behind the prediction, in words an accountant can use. */
export const confidenceOf = (p: Pick<PredictionRow, "method" | "history_count">): Confidence => {
  const n = p.history_count ?? 0;
  if (p.method === "customer_median") return { kind: "own", label: `Dựa trên ${n} hóa đơn khách này đã trả`, short: `${n} lần trả trước` };
  if (p.method === "global_median") return { kind: "shared", label: `Khách này mới có ${n} hóa đơn đã trả, nên dùng thói quen chung của mọi khách`, short: "ít lịch sử" };
  return { kind: "none", label: "Chưa có lịch sử thanh toán: giả định khách trả đúng hạn", short: "chưa có lịch sử" };
};

export const describeDelay = (delay: number): string =>
  delay > 0 ? `thường trả trễ khoảng ${delay} ngày so với hạn` : delay < 0 ? `thường trả sớm khoảng ${-delay} ngày so với hạn` : "thường trả đúng hạn";

export type PredictionSummary = { usualDelay: number; spreadDays: number; confidence: Confidence; sentence: string };

export const summarizePrediction = (p: PredictionRow, dueIso: string, asOfIso: string): PredictionSummary => {
  const usualDelay = daysBetween(dueIso, p.predicted_date_p50);
  const spreadDays = daysBetween(p.predicted_date_p25, p.predicted_date_p75);
  const overdue = daysBetween(dueIso, asOfIso);
  const range = `Ngày trả có thể từ ${shortDay(p.predicted_date_p25)} đến ${shortDay(p.predicted_date_p75)}.`;
  const sentence = p.overdue_adjusted
    ? "Hóa đơn đã quá hạn lâu hơn mọi lần khách trả trước, nên ngày dự đoán được tính từ hôm nay."
    : overdue > 0
      // Still unpaid: only earlier payments that were at least this late are relevant, so the figure is not the customer's habit overall.
      ? `Hóa đơn đã quá hạn ${overdue} ngày. Trong các lần trả trước còn trễ hơn mức này, khách thường trả sau khoảng ${usualDelay} ngày kể từ hạn. ${range}`
      : `Khách này ${describeDelay(usualDelay)}. ${range}`;
  return { usualDelay, spreadDays, confidence: confidenceOf(p), sentence };
};

/** Positions (0..1) on a line that holds the due date, today and the three predicted dates, with two days of margin. */
export const timelineScale = (dueIso: string, asOfIso: string, p: PredictionRow) => {
  const days = [dueIso, asOfIso, p.predicted_date_p25, p.predicted_date_p50, p.predicted_date_p75].map(dayNumber);
  const lo = Math.min(...days) - 2;
  const hi = Math.max(...days) + 2;
  const span = Math.max(hi - lo, 1);
  return { lo, hi, at: (iso: string): number => (dayNumber(iso) - lo) / span };
};

const amountOf = (r: InvoiceRow) => Number(r.remaining_amount) || 0;

/** Open invoices expected to be paid soonest (usual date from today on), largest first among equal dates. */
export const nextToPay = (rows: InvoiceRow[], asOfIso: string, n = 3): InvoiceRow[] =>
  rows
    .filter(r => r.prediction && amountOf(r) > 0 && daysBetween(asOfIso, r.prediction.predicted_date_p50) >= 0)
    .sort((a, b) => daysBetween(b.prediction!.predicted_date_p50, a.prediction!.predicted_date_p50) || amountOf(b) - amountOf(a))
    .slice(0, n);

const delayOf = (r: InvoiceRow) => daysBetween(r.due_date, r.prediction!.predicted_date_p50);

/** Not overdue yet, but the customer usually pays after the due date: the biggest expected delays first. */
export const likelyLate = (rows: InvoiceRow[], n = 3): InvoiceRow[] =>
  rows
    .filter(r => r.prediction && amountOf(r) > 0 && r.days_overdue <= 0 && delayOf(r) > 0)
    .sort((a, b) => delayOf(b) - delayOf(a) || amountOf(b) - amountOf(a))
    .slice(0, n);
