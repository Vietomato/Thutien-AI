// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseInline, parseMarkdown } from "./chatMarkdown.ts";

test("bold, italic and code inside a sentence", () => {
  assert.deepEqual(parseInline("Tuần **2** thiếu *khoảng* `x`."), [
    { text: "Tuần " }, { text: "2", bold: true }, { text: " thiếu " }, { text: "khoảng", italic: true }, { text: " " }, { text: "x", code: true }, { text: "." }]);
});

test("a lone asterisk or a multiplication sign is left alone", () => {
  assert.equal(parseInline("2 * 3 = 6")[0].text, "2 * 3 = 6");
});

test("lists, headings and paragraphs", () => {
  const blocks = parseMarkdown("## Kết quả\nHai điểm:\n- một\n- **hai**\n\n1. a\n2. b");
  assert.deepEqual(blocks.map(b => b.kind), ["p", "p", "ul", "ol"]);
  assert.equal((blocks[2] as any).items.length, 2);
  assert.equal((blocks[0] as any).inline[0].bold, true);
});

test("pipe tables", () => {
  const blocks = parseMarkdown("| Tuần | Thiếu |\n|---|---:|\n| 2 | **1,8 tỷ** |\n| 3 | 0 |\n\nHết.");
  assert.equal(blocks[0].kind, "table");
  const table = blocks[0] as any;
  assert.equal(table.head.length, 2); assert.equal(table.rows.length, 2); assert.equal(table.rows[0][1][0].bold, true);
  assert.equal(blocks[1].kind, "p");
});

test("html is never interpreted: it stays text", () => {
  const blocks = parseMarkdown("<img src=x onerror=alert(1)> **b**");
  assert.equal((blocks[0] as any).inline[0].text, "<img src=x onerror=alert(1)> ");
});
