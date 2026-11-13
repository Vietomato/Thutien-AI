// Pure helpers for the F4 forecast screen: no React, no network. Everything here is plain arithmetic on numbers the
// backend already computed, so it can be tested on its own (npm test).

export type WeekRow = {
  week_start: string;
  receipt_p25: number;
  receipt_p50: number;
  receipt_p75: number;
  receipt_expected?: number;       // probability-weighted receipts; absent on an older API
  obligations: number;
  gap_p75: number;
};

export type ScenarioKey = "early" | "usual" | "late";

export type Scenario = {
  key: ScenarioKey;
  field: "receipt_p25" | "receipt_expected" | "receipt_p75";
  fallback?: "receipt_p50";        // used when the API does not send `field`
  label: string;
  short: string;
  statistic: string;
  hint: string;
};

// P25 / P50 / P75 are the quantiles of how late each customer used to pay. In everyday words:
// early = money arrives sooner than in 3 of 4 past cases, late = later than in 3 of 4 past cases.
export const SCENARIOS: readonly Scenario[] = [
  { key: "early", field: "receipt_p25", label: "Khách trả sớm", short: "Sớm", statistic: "Tiền về sớm",
    hint: "Tiền về sớm: trong 4 lần trước, chỉ 1 lần khách trả nhanh hơn mức này." },
  { key: "usual", field: "receipt_expected", fallback: "receipt_p50", label: "Khách trả theo thói quen", short: "Thói quen", statistic: "Kỳ vọng theo xác suất",
    hint: "Kỳ vọng: mỗi hóa đơn được chia vào các tuần khách có thể trả, theo xác suất rút ra từ lịch sử trả của khách đó." },
  { key: "late", field: "receipt_p75", label: "Khách trả muộn", short: "Muộn", statistic: "Tiền về muộn",
    hint: "Tiền về muộn: trong 4 lần trước, chỉ 1 lần khách trả chậm hơn mức này. Cảnh báo thiếu tiền dùng kịch bản này." },
] as const;

export const LATE = SCENARIOS[2];

export const toNumber = (value: unknown): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
};

export const receiptOf = (week: WeekRow, scenario: Scenario): number =>
  toNumber(week[scenario.field] ?? (scenario.fallback ? week[scenario.fallback] : undefined));

/** Money going out that the receipts of the chosen scenario do not cover in that week (never negative). */
export const gapOf = (week: WeekRow, scenario: Scenario): number =>
  Math.max(toNumber(week.obligations) - receiptOf(week, scenario), 0);

// ---- dates (ISO yyyy-mm-dd, calendar arithmetic in UTC so time zones never shift a day) -------------------------

const parts = (iso: string): [number, number, number] => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
};

export const addDays = (iso: string, days: number): string => {
  const [y, m, d] = parts(iso);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
};

export const shortDate = (iso: string): string => {
  const [, m, d] = parts(iso);
  return `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
};

/** "16/11 – 22/11": the week that starts on `iso` and runs seven days. */
export const weekRange = (iso: string): string => `${shortDate(iso)} – ${shortDate(addDays(iso, 6))}`;

// ---- money -------------------------------------------------------------------------------------------------------

const decimal = (value: number, digits: number) =>
  new Intl.NumberFormat("vi-VN", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);

const digitsFor = (scaled: number) => (Math.abs(scaled) < 10 ? 2 : Math.abs(scaled) < 100 ? 1 : 0);

/** 2.569.977.800 -> "2,57 tỷ", 726.000.000 -> "726 tr", 6.500.000 -> "6,5 tr", 0 -> "0". */
export const compactMoney = (value: number): string => {
  const v = toNumber(value);
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${decimal(v / 1e9, digitsFor(v / 1e9))} tỷ`;
  if (abs >= 1e6) return `${decimal(v / 1e6, digitsFor(v / 1e6) === 2 ? 1 : digitsFor(v / 1e6))} tr`;
  if (abs >= 1e3) return `${decimal(v / 1e3, 0)} nghìn`;
  return v === 0 ? "0" : `${decimal(v, 0)} đ`;
};

// ---- chart scale -------------------------------------------------------------------------------------------------

export type Scale = { top: number; step: number; ticks: number[] };

/** Round-number gridlines (1, 2, 2.5, 5 x 10^k) with about `target` intervals; `top` is never below `max`. */
export const niceScale = (max: number, target = 4): Scale => {
  if (!(max > 0)) return { top: 1, step: 1, ticks: [0, 1] };
  const raw = max / target;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = ([1, 2, 2.5, 5, 10].map(m => m * pow).find(s => s >= raw)) as number;
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step * 1e-9; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { top, step, ticks };
};

// ---- summaries ---------------------------------------------------------------------------------------------------

export type Summary = {
  weeks: number;
  riskyWeeks: number;
  worstIndex: number;
  worstGap: number;
  totalObligations: number;
  totalReceipts: Record<ScenarioKey, number>;
};

/** Numbers for the headline cards. Warnings follow the pessimistic scenario, as in the rest of the app. */
export const summarize = (weeks: WeekRow[], scenario: Scenario = LATE): Summary => {
  let worstIndex = -1;
  let worstGap = 0;
  let riskyWeeks = 0;
  weeks.forEach((w, i) => {
    const gap = gapOf(w, scenario);
    if (gap > 0) riskyWeeks += 1;
    if (gap > worstGap) { worstGap = gap; worstIndex = i; }
  });
  const sum = (pick: (w: WeekRow) => number) => weeks.reduce((s, w) => s + pick(w), 0);
  return {
    weeks: weeks.length, riskyWeeks, worstIndex, worstGap,
    totalObligations: sum(w => toNumber(w.obligations)),
    totalReceipts: {
      early: sum(w => receiptOf(w, SCENARIOS[0])),
      usual: sum(w => receiptOf(w, SCENARIOS[1])),
      late: sum(w => receiptOf(w, SCENARIOS[2])),
    },
  };
};

/** The week to show before the user picks one: the one with the biggest shortfall, else the first. */
export const defaultWeek = (weeks: WeekRow[], scenario: Scenario): number => {
  const { worstIndex } = summarize(weeks, scenario);
  return worstIndex >= 0 ? worstIndex : 0;
};

export const hasAnyMoney = (weeks: WeekRow[]): boolean =>
  weeks.some(w => toNumber(w.receipt_p25) + toNumber(w.receipt_p50) + toNumber(w.receipt_p75) + toNumber(w.receipt_expected) + toNumber(w.obligations) > 0);
