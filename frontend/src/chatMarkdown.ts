// A tiny, safe markdown subset for the assistant's answers: paragraphs, bullet and numbered lists, pipe tables,
// **bold**, *italic* and `code`. It produces plain data; the component builds elements from it (no HTML injection).
export type Inline = { text: string; bold?: boolean; italic?: boolean; code?: boolean };
export type Block =
  | { kind: "p"; inline: Inline[] }
  | { kind: "ul" | "ol"; items: Inline[][] }
  | { kind: "table"; head: Inline[][]; rows: Inline[][][] };

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|(?<![*\w])\*(?!\s)([^*]+?)\*(?![*\w])/g;
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ text: m[1], bold: true });
    else if (m[2] !== undefined) out.push({ text: m[2], code: true });
    else out.push({ text: m[3], italic: true });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out.length ? out : [{ text: "" }];
}

const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());
const isDivider = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => { if (paragraph.length) { blocks.push({ kind: "p", inline: parseInline(paragraph.join(" ")) }); paragraph = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) { flush(); continue; }
    if (line.includes("|") && i + 1 < lines.length && isDivider(lines[i + 1])) {
      flush();
      const head = cells(line).map(parseInline), rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]).map(parseInline));
      i--;
      blocks.push({ kind: "table", head, rows });
      continue;
    }
    const bullet = /^\s*(?:[-*•])\s+(.*)$/.exec(line), numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flush();
      const kind = bullet ? "ul" : "ol", items: Inline[][] = [];
      while (i < lines.length) {
        const m = (kind === "ul" ? /^\s*(?:[-*•])\s+(.*)$/ : /^\s*\d+[.)]\s+(.*)$/).exec(lines[i]);
        if (!m) break;
        items.push(parseInline(m[1]));
        i++;
      }
      i--;
      blocks.push({ kind, items });
      continue;
    }
    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
    if (heading) { flush(); blocks.push({ kind: "p", inline: parseInline(heading[1]).map(x => ({ ...x, bold: true })) }); continue; }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}
