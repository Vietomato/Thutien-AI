// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  confidenceOf, daysBetween, describeDelay, likelyLate, nextToPay, shortDay, summarizePrediction, timelineScale,
  type InvoiceRow, type PredictionRow,
} from "./predictionMath.ts";

const pred = (p25: string, p50: string, p75: string, extra: Partial<PredictionRow> = {}): PredictionRow =>
  ({ predicted_date_p25: p25, predicted_date_p50: p50, predicted_date_p75: p75, method: "customer_median", history_count: 12, ...extra });

const invoice = (id: string, due: string, overdue: number, amount: number, prediction: PredictionRow | null): InvoiceRow =>
  ({ invoice_id: id, display_name: `Khach ${id}`, remaining_amount: amount, due_date: due, days_overdue: overdue, prediction });

test("days between dates cross months, years and leap days", () => {
  assert.equal(daysBetween("2026-11-09", "2026-11-22"), 13);
  assert.equal(daysBetween("2026-12-28", "2027-01-03"), 6);
  assert.equal(daysBetween("2028-02-27", "2028-03-01"), 3);
  assert.equal(daysBetween("2026-11-22", "2026-11-09"), -13);
  assert.equal(shortDay("2026-11-22"), "22/11");
});

test("the delay is described in words for late, early and on time", () => {
  assert.equal(describeDelay(5), "thường trả trễ khoảng 5 ngày so với hạn");
  assert.equal(describeDelay(-3), "thường trả sớm khoảng 3 ngày so với hạn");
  assert.equal(describeDelay(0), "thường trả đúng hạn");
});

test("confidence says how much history is behind the prediction", () => {
  assert.equal(confidenceOf({ method: "customer_median", history_count: 12 }).kind, "own");
  assert.match(confidenceOf({ method: "customer_median", history_count: 12 }).label, /12 hóa đơn/);
  assert.equal(confidenceOf({ method: "global_median", history_count: 2 }).kind, "shared");
  assert.equal(confidenceOf({ method: "no_history", history_count: 0 }).kind, "none");
  assert.equal(confidenceOf({}).kind, "none");
});

test("the summary gives the usual delay, the spread and a sentence a person can read", () => {
  const s = summarizePrediction(pred("2026-11-18", "2026-11-22", "2026-12-03"), "2026-11-15", "2026-11-09");
  assert.equal(s.usualDelay, 7);
  assert.equal(s.spreadDays, 15);
  assert.match(s.sentence, /trễ khoảng 7 ngày/);
  assert.match(s.sentence, /18\/11 đến 03\/12/);
});

test("an invoice already later than anything on record says its date is counted from today", () => {
  const s = summarizePrediction(pred("2026-11-10", "2026-11-12", "2026-11-16", { overdue_adjusted: true }), "2026-09-01", "2026-11-09");
  assert.match(s.sentence, /tính từ hôm nay/);
});

test("the timeline holds every date inside 0..1 and keeps their order", () => {
  const p = pred("2026-11-18", "2026-11-22", "2026-12-03");
  const scale = timelineScale("2026-11-15", "2026-11-09", p);
  const positions = ["2026-11-09", "2026-11-15", "2026-11-18", "2026-11-22", "2026-12-03"].map(scale.at);
  assert.ok(positions.every(x => x > 0 && x < 1));
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
});

test("the timeline never divides by zero when everything is the same day", () => {
  const p = pred("2026-11-09", "2026-11-09", "2026-11-09");
  const scale = timelineScale("2026-11-09", "2026-11-09", p);
  assert.ok(Number.isFinite(scale.at("2026-11-09")));
});

test("next to pay: soonest usual date first, today counts, past dates and no-prediction rows do not", () => {
  const rows = [
    invoice("A", "2026-11-01", 8, 100, pred("2026-11-10", "2026-11-12", "2026-11-20")),
    invoice("B", "2026-11-05", 4, 500, pred("2026-11-09", "2026-11-09", "2026-11-15")),     // today
    invoice("C", "2026-11-05", 4, 900, null),                                                   // disputed
    invoice("D", "2026-10-01", 39, 50, pred("2026-11-01", "2026-11-05", "2026-11-07")),      // usual date already past
    invoice("E", "2026-11-05", 4, 700, pred("2026-11-12", "2026-11-12", "2026-11-14")),      // same day as A, larger
  ];
  assert.deepEqual(nextToPay(rows, "2026-11-09", 3).map(r => r.invoice_id), ["B", "E", "A"]);
});

test("likely late: not overdue yet, but the usual date is after the due date; longest delay first", () => {
  const rows = [
    invoice("A", "2026-11-20", -11, 100, pred("2026-11-22", "2026-11-25", "2026-12-01")),   // +5
    invoice("B", "2026-11-20", -11, 100, pred("2026-11-19", "2026-11-20", "2026-11-21")),   // on time: not listed
    invoice("C", "2026-11-30", -21, 300, pred("2026-12-05", "2026-12-12", "2026-12-20")),   // +12
    invoice("D", "2026-11-01", 8, 999, pred("2026-11-12", "2026-11-14", "2026-11-18")),     // already overdue: not listed
    invoice("E", "2026-11-25", -16, 800, pred("2026-11-28", "2026-11-30", "2026-12-04")),   // +5, larger than A
  ];
  assert.deepEqual(likelyLate(rows, 5).map(r => r.invoice_id), ["C", "E", "A"]);
});

test("an invoice that is already overdue is described by what happened to similar late invoices, not as the customer's habit", () => {
  const s = summarizePrediction(pred("2026-11-15", "2026-11-22", "2026-11-29"), "2026-10-10", "2026-11-09");
  assert.match(s.sentence, /quá hạn 30 ngày/);
  assert.match(s.sentence, /khoảng 43 ngày kể từ hạn/);
  assert.doesNotMatch(s.sentence, /thường trả trễ khoảng/);
});
