import type { ReactNode } from "react"

/**
 * Minimal Markdown for Copilot answers: paragraphs, headings, **bold**, `code`,
 * bullet/numbered lists and GFM tables. Builds React elements only (no HTML strings),
 * so model or template text can never inject markup.
 */
export function CopilotMarkdown({ text }: { text: string }) {
  return <div className="space-y-2 leading-6">{renderBlocks(text)}</div>
}

type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }

const BULLET_RE = /^\s*[-*•]\s+(.*)$/
const ORDERED_RE = /^\s*\d+[.)]\s+(.*)$/
const HEADING_RE = /^\s*#{1,4}\s+(.*)$/
const TABLE_ROW_RE = /^\s*\|.*\|\s*$/
const TABLE_DIVIDER_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n")
  const blocks: Block[] = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }
    const heading = HEADING_RE.exec(line)
    if (heading) {
      blocks.push({ kind: "heading", text: heading[1] })
      index += 1
      continue
    }
    if (TABLE_ROW_RE.test(line) && index + 1 < lines.length && TABLE_DIVIDER_RE.test(lines[index + 1])) {
      const header = splitRow(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && TABLE_ROW_RE.test(lines[index])) {
        rows.push(splitRow(lines[index]))
        index += 1
      }
      blocks.push({ kind: "table", header, rows })
      continue
    }
    const listMatch = BULLET_RE.exec(line) ?? ORDERED_RE.exec(line)
    if (listMatch) {
      const ordered = !BULLET_RE.test(line)
      const items: string[] = []
      while (index < lines.length) {
        const match = (ordered ? ORDERED_RE : BULLET_RE).exec(lines[index])
        if (!match) {
          break
        }
        items.push(match[1])
        index += 1
      }
      blocks.push({ kind: "list", ordered, items })
      continue
    }
    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !HEADING_RE.test(lines[index]) &&
      !BULLET_RE.test(lines[index]) &&
      !ORDERED_RE.test(lines[index]) &&
      !TABLE_ROW_RE.test(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    if (paragraph.length) {
      blocks.push({ kind: "paragraph", lines: paragraph })
    } else {
      // A lone table-looking row without a divider: show it as text.
      blocks.push({ kind: "paragraph", lines: [line] })
      index += 1
    }
  }
  return blocks
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim())
}

function renderBlocks(text: string): ReactNode[] {
  return parseBlocks(text).map((block, index) => {
    switch (block.kind) {
      case "heading":
        return (
          <p key={index} className="font-semibold text-foreground">
            {renderInline(block.text)}
          </p>
        )
      case "list": {
        const items = block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)
        return block.ordered ? (
          <ol key={index} className="list-decimal space-y-1 pl-5">
            {items}
          </ol>
        ) : (
          <ul key={index} className="list-disc space-y-1 pl-5">
            {items}
          </ul>
        )
      }
      case "table":
        return (
          <div key={index} className="overflow-x-auto rounded-lg border border-border/60">
            <table className="w-full border-collapse text-xs">
              <thead className="bg-muted/50">
                <tr>
                  {block.header.map((cell, cellIndex) => (
                    <th key={cellIndex} scope="col" className="px-2 py-1.5 text-left font-semibold">
                      {renderInline(cell)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, rowIndex) => (
                  <tr key={rowIndex} className="border-t border-border/50">
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex} className="px-2 py-1.5 align-top">
                        {renderInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      case "paragraph":
        return (
          <p key={index} className="whitespace-pre-wrap">
            {block.lines.map((line, lineIndex) => (
              <span key={lineIndex}>
                {lineIndex > 0 ? "\n" : null}
                {renderInline(line)}
              </span>
            ))}
          </p>
        )
    }
  })
}

const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`)/g

function renderInline(text: string): ReactNode[] {
  return text.split(INLINE_RE).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={index} className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      )
    }
    return part
  })
}
