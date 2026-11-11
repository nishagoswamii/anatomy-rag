"use client";

import type { ReactNode } from "react";
import type { Citation } from "@/lib/api";

export type Segment = { text: string; citations: Citation[] };

type Token = { kind: "text"; text: string } | { kind: "cite"; citations: Citation[] };

/** Render **bold** spans inside a run of text. */
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

function uniqueBySource(citations: Citation[]): Citation[] {
  const seen = new Set<number>();
  return citations.filter((c) => !seen.has(c.source_index) && seen.add(c.source_index));
}

/**
 * Lays out streamed text segments as paragraphs and bullet lists, with a
 * citation chip after each cited segment. Only light Markdown is supported
 * (bold, "-"/"*"/"1." lists, "#" headings), which is all the prompt asks for.
 */
export function Answer({
  segments,
  onCite,
}: {
  segments: Segment[];
  onCite: (citation: Citation) => void;
}) {
  const tokens: Token[] = [];
  for (const seg of segments) {
    if (seg.text) tokens.push({ kind: "text", text: seg.text });
    if (seg.citations.length) tokens.push({ kind: "cite", citations: uniqueBySource(seg.citations) });
  }

  // Split tokens into lines, keeping chips attached to the line they follow.
  const lines: Token[][] = [[]];
  for (const t of tokens) {
    if (t.kind === "cite") {
      lines[lines.length - 1].push(t);
      continue;
    }
    t.text.split("\n").forEach((piece, i) => {
      if (i > 0) lines.push([]);
      if (piece) lines[lines.length - 1].push({ kind: "text", text: piece });
    });
  }

  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: ReactNode[] } | null = null;
  const flushList = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(
      <Tag key={`l${blocks.length}`} className={list.ordered ? "list-decimal pl-5 space-y-1" : "list-disc pl-5 space-y-1"}>
        {list.items}
      </Tag>,
    );
    list = null;
  };

  lines.forEach((line, li) => {
    if (!line.length) {
      flushList();
      return;
    }
    const first = line[0];
    let prefix: "ul" | "ol" | "h" | null = null;
    if (first.kind === "text") {
      const m = first.text.match(/^\s*([-*]|\d+\.)\s+/);
      const h = first.text.match(/^\s*#{1,4}\s+/);
      if (m) {
        prefix = /\d/.test(m[1]) ? "ol" : "ul";
        line = [{ kind: "text", text: first.text.slice(m[0].length) }, ...line.slice(1)];
      } else if (h) {
        prefix = "h";
        line = [{ kind: "text", text: first.text.slice(h[0].length) }, ...line.slice(1)];
      }
    }
    const content = line.map((t, ti) =>
      t.kind === "text" ? (
        <span key={ti}>{inline(t.text, `${li}-${ti}`)}</span>
      ) : (
        <span key={ti} className="whitespace-nowrap">
          {t.citations.map((c) => (
            <button
              key={c.source_index}
              type="button"
              onClick={() => onCite(c)}
              className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-teal-100 px-1 align-text-top text-xs font-semibold text-teal-800 hover:bg-teal-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:bg-teal-900 dark:text-teal-100"
              aria-label={`Show source ${c.source_index + 1}`}
            >
              {c.source_index + 1}
            </button>
          ))}
        </span>
      ),
    );
    if (prefix === "ul" || prefix === "ol") {
      const ordered = prefix === "ol";
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(<li key={li}>{content}</li>);
    } else {
      flushList();
      blocks.push(
        prefix === "h" ? (
          <p key={li} className="font-semibold">
            {content}
          </p>
        ) : (
          <p key={li}>{content}</p>
        ),
      );
    }
  });
  flushList();

  return <div className="space-y-3 leading-relaxed">{blocks}</div>;
}
