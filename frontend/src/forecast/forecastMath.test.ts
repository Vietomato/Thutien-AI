// Run with: npm test (Node's built-in test runner, no extra packages).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  LATE, SCENARIOS, addDays, compactMoney, defaultWeek, gapOf, hasAnyMoney, niceScale, receiptOf, shortDate,
  summarize, toNumber, weekRange, type WeekRow,
} from "./forecastMath.ts";

const M = 1_000_000;
const week = (start: string, p25: number, p50: number, p75: number, out: number): WeekRow => ({
  week_start: start, receipt_p25: p25, receipt_p50: p50, receipt_p75: p75, obligations: out,
  gap_p75: Math.max(out - p75, 0),
});

test("scenarios map to the three quantiles and warn on the late one", () => {
  assert.deepEqual(SCENARIOS.map(s => s.field), ["receipt_p25", "receipt_expected", "receipt_p75"]);
  assert.equal(LATE.field, "receipt_p75");
});

test("compactMoney writes billions, millions and thousands the way an accountant reads them", () => {
  assert.equal(compactMoney(2_569_977_800), "2,57 tỷ");
  assert.equal(compactMoney(7_337_977_800), "7,34 tỷ");
  assert.equal(compactMoney(12_400_000_000), "12,4 tỷ");
  assert.equal(compactMoney(726 * M), "726 tr");
  assert.equal(compactMoney(65 * M), "65 tr");
  assert.equal(compactMoney(6_500_000), "6,5 tr");
  assert.equal(compactMoney(1_000_000), "1 tr");
  assert.equal(compactMoney(250_000), "250 nghìn");
  assert.equal(compactMoney(500), "500 đ");
  assert.equal(compactMoney(0), "0");
  assert.equal(compactMoney(-1_840_000_000), "-1,84 tỷ");
});

test("toNumber never lets a bad value reach the screen", () => {
  assert.equal(toNumber(undefined), 0);
  assert.equal(toNumber("abc"), 0);
  assert.equal(toNumber("42"), 42);
  assert.equal(toNumber(NaN), 0);
});

test("weeks are shown as a seven day range, across month, year and leap day", () => {
  assert.equal(weekRange("2026-11-16"), "16/11 – 22/11");
  assert.equal(weekRange("2026-11-30"), "30/11 – 06/12");
  assert.equal(weekRange("2026-12-28"), "28/12 – 03/01");
  assert.equal(weekRange("2028-02-27"), "27/02 – 04/03");        // 2028 is a leap year
  assert.equal(shortDate("2026-01-05"), "05/01");
  assert.equal(addDays("2026-02-27", 3), "2026-03-02");
});

test("a week is short only when the chosen scenario brings in less than goes out", () => {
  const w = week("2026-11-16", 681 * M, 1125 * M, 726 * M, 2570 * M);
  assert.equal(gapOf(w, SCENARIOS[2]), 2570 * M - 726 * M);          // late
  assert.equal(gapOf(w, SCENARIOS[1]), 2570 * M - 1125 * M);         // usual
  assert.equal(gapOf(w, SCENARIOS[0]), 2570 * M - 681 * M);          // early
  assert.equal(gapOf(week("x", 0, 0, 500 * M, 100 * M), LATE), 0);   // covered: never negative
  assert.equal(receiptOf(w, SCENARIOS[1]), 1125 * M);
});

test("the late-scenario gap agrees with the gap_p75 the backend sends", () => {
  const w = week("2026-11-09", 1644 * M, 1171 * M, 894 * M, 1045 * M);
  assert.equal(gapOf(w, LATE), w.gap_p75);
});

test("niceScale gives round gridlines that always contain the data", () => {
  for (const max of [1, 7, 130, 999_999, 1_045_000_000, 2_570_000_000, 7_337_977_800, 42_000_000_000]) {
    const s = niceScale(max);
    assert.ok(s.top >= max, `top ${s.top} must be >= ${max}`);
    assert.equal(s.ticks[0], 0);
    assert.equal(s.ticks[s.ticks.length - 1], s.top);
    assert.ok(s.ticks.length >= 3 && s.ticks.length <= 7, `${s.ticks.length} ticks for ${max}`);
    s.ticks.slice(1).forEach((t, i) => assert.ok(Math.abs(t - s.ticks[i] - s.step) < s.step * 1e-6));
  }
  assert.deepEqual(niceScale(2_570_000_000).ticks, [0, 1e9, 2e9, 3e9]);
  assert.deepEqual(niceScale(0).ticks, [0, 1]);                       // nothing to draw, but never a crash
});

test("summarize counts risky weeks and finds the worst one", () => {
  const weeks = [
    week("2026-11-09", 1644 * M, 1171 * M, 894 * M, 1045 * M),       // short by 151
    week("2026-11-16", 681 * M, 1125 * M, 726 * M, 2570 * M),        // short by 1844
    week("2026-11-23", 867 * M, 700 * M, 995 * M, 882 * M),          // covered
  ];
  const s = summarize(weeks);
  assert.equal(s.riskyWeeks, 2);
  assert.equal(s.worstIndex, 1);
  assert.equal(s.worstGap, 1844 * M);
  assert.equal(s.totalObligations, (1045 + 2570 + 882) * M);
  assert.equal(s.totalReceipts.late, (894 + 726 + 995) * M);
  assert.equal(s.totalReceipts.early, (1644 + 681 + 867) * M);
});

test("with no shortfall there is no worst week and the first week is shown", () => {
  const weeks = [week("2026-11-09", 5, 5, 5, 1), week("2026-11-16", 5, 5, 5, 1)];
  const s = summarize(weeks);
  assert.equal(s.riskyWeeks, 0);
  assert.equal(s.worstIndex, -1);
  assert.equal(defaultWeek(weeks, LATE), 0);
});

test("the default week is the one with the biggest shortfall of the chosen scenario", () => {
  const weeks = [week("a", 0, 0, 0, 10), week("b", 0, 0, 0, 90), week("c", 0, 0, 0, 40)];
  assert.equal(defaultWeek(weeks, LATE), 1);
});

test("an empty or all-zero forecast is recognised so the screen can say so", () => {
  assert.equal(hasAnyMoney([]), false);
  assert.equal(hasAnyMoney([week("a", 0, 0, 0, 0)]), false);
  assert.equal(hasAnyMoney([week("a", 0, 0, 0, 1)]), true);
});

test("the middle line uses the probability-weighted figure and falls back to the median line for an older API", () => {
  const usual = SCENARIOS[1];
  const withExpected = { ...week("2026-11-09", 100 * M, 200 * M, 300 * M, 0), receipt_expected: 250 * M };
  assert.equal(receiptOf(withExpected, usual), 250 * M);
  assert.equal(receiptOf(week("2026-11-09", 100 * M, 200 * M, 300 * M, 0), usual), 200 * M);   // no receipt_expected sent
  assert.equal(summarize([withExpected]).totalReceipts.usual, 250 * M);
  assert.equal(summarize([withExpected]).totalReceipts.early, 100 * M);
  assert.equal(summarize([withExpected]).totalReceipts.late, 300 * M);
});

test("a forecast that only has the expected figure still counts as having money", () => {
  assert.equal(hasAnyMoney([{ ...week("a", 0, 0, 0, 0), receipt_expected: 5 }]), true);
});
