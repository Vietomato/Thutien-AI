// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatUpdated } from "./updatedAt.ts";

const local = (y: number, m: number, d: number, h: number, min: number) => new Date(y, m - 1, d, h, min);

test("today shows only the time", () => {
  assert.equal(formatUpdated(local(2026, 11, 13, 14, 32).toISOString(), local(2026, 11, 13, 20, 0)), "14:32");
});

test("another day shows the date as well", () => {
  assert.equal(formatUpdated(local(2026, 11, 12, 9, 5).toISOString(), local(2026, 11, 13, 20, 0)), "12/11 09:05");
});

test("a missing or broken value shows nothing", () => {
  assert.equal(formatUpdated(undefined), "");
  assert.equal(formatUpdated(""), "");
  assert.equal(formatUpdated("not a date"), "");
});
