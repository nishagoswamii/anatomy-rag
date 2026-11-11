"use client";

import { useEffect, useRef, useState } from "react";
import { Answer, type Segment } from "@/components/Answer";
import { SourcePanel } from "@/components/SourcePanel";
import {
  ApiError,
  type ChatEvent,
  type Citation,
  type HistoryTurn,
  type Source,
  streamChat,
  waitForBackend,
} from "@/lib/api";

type Status = "searching" | "streaming" | "done" | "out_of_scope" | "error";

type UserMsg = { id: number; role: "user"; text: string };
type BotMsg = {
  id: number;
  role: "assistant";
  segments: Record<number, Segment>;
  sources: Source[];
  status: Status;
  notice?: string;
  uncited?: boolean;
  truncated?: boolean;
};
type Msg = UserMsg | BotMsg;

const STARTERS = [
  "How do the lungs exchange oxygen and carbon dioxide?",
  "What makes the heart beat on its own?",
  "How do the kidneys concentrate urine?",
  "What is the difference between innate and adaptive immunity?",
];
const MAX_CHARS = 1000;

function answerText(m: BotMsg): string {
  if (m.status === "out_of_scope") return m.notice ?? "";
  return Object.keys(m.segments)
    .map(Number)
    .sort((a, b) => a - b)
    .map((k) => m.segments[k].text)
    .join("");
}

/** Completed question/answer pairs as plain text, for follow-up questions. */
function buildHistory(messages: Msg[]): HistoryTurn[] {
  const turns: HistoryTurn[] = [];
  for (let i = 0; i + 1 < messages.length; i += 2) {
    const u = messages[i];
    const a = messages[i + 1];
    if (u.role !== "user" || a.role !== "assistant") continue;
    if (a.status !== "done" && a.status !== "out_of_scope") continue;
    const text = answerText(a);
    if (!text) continue;
    turns.push({ role: "user", text: u.text }, { role: "assistant", text: text.slice(0, 8000) });
  }
  return turns.slice(-12);
}

function applyEvent(m: BotMsg, e: ChatEvent): BotMsg {
  switch (e.type) {
    case "sources":
      return { ...m, sources: e.sources, status: "streaming" };
    case "text": {
      const seg = m.segments[e.block] ?? { text: "", citations: [] };
      return { ...m, segments: { ...m.segments, [e.block]: { ...seg, text: seg.text + e.text } } };
    }
    case "citation": {
      const seg = m.segments[e.block] ?? { text: "", citations: [] };
      const c: Citation = {
        source_index: e.source_index,
        start_block: e.start_block,
        end_block: e.end_block,
        cited_text: e.cited_text,
      };
      return { ...m, segments: { ...m.segments, [e.block]: { ...seg, citations: [...seg.citations, c] } } };
    }
    case "out_of_scope":
      return { ...m, status: "out_of_scope", notice: e.message };
    case "reset":
      return { ...m, segments: {} };
    case "error":
      return { ...m, status: "error", notice: e.message };
    case "done":
      if (m.status === "error" || m.status === "out_of_scope") return m;
      return { ...m, status: "done", uncited: e.uncited, truncated: e.truncated };
  }
}

export function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [waking, setWaking] = useState(false);
  const [active, setActive] = useState<{ msgId: number; citation: Citation } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const nextId = useRef(1);

  // The free host sleeps when idle; show a notice if the first health check is slow.
  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => setWaking(true), 2000);
    waitForBackend(ctrl.signal).then(() => {
      clearTimeout(timer);
      setWaking(false);
    });
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const history = buildHistory(messages);
    const userMsg: UserMsg = { id: nextId.current++, role: "user", text: q };
    const botId = nextId.current++;
    const botMsg: BotMsg = { id: botId, role: "assistant", segments: {}, sources: [], status: "searching" };
    setMessages((ms) => [...ms, userMsg, botMsg]);
    setInput("");
    setBusy(true);

    const update = (fn: (m: BotMsg) => BotMsg) =>
      setMessages((ms) => ms.map((m) => (m.id === botId && m.role === "assistant" ? fn(m) : m)));

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamChat(q, history, (e) => update((m) => applyEvent(m, e)), ctrl.signal);
      update((m) =>
        m.status === "searching" || m.status === "streaming"
          ? { ...m, status: "error", notice: "The answer was interrupted. Please try again." }
          : m,
      );
    } catch (err) {
      const aborted = ctrl.signal.aborted;
      const message = aborted
        ? "Stopped."
        : err instanceof ApiError
          ? err.message
          : "Couldn't reach the server. Please try again.";
      update((m) => ({ ...m, status: "error", notice: message }));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  const activeMsg = active
    ? (messages.find((m) => m.id === active.msgId && m.role === "assistant") as BotMsg | undefined)
    : undefined;

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        {waking && (
          <div role="status" className="bg-amber-50 px-4 py-2 text-center text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
            Waking up the server. The free host sleeps when idle, so the first answer can take up to a minute.
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.length === 0 && (
              <div className="py-10 text-center">
                <h2 className="text-2xl font-semibold tracking-tight">Ask the anatomy textbook</h2>
                <p className="mx-auto mt-2 max-w-xl text-zinc-600 dark:text-zinc-400">
                  Answers come only from <em>Anatomy and Physiology 2e</em> (OpenStax), with every claim
                  linked to the passage it came from. Questions the book doesn&apos;t cover get a clear
                  &ldquo;not in this book&rdquo;.
                </p>
                <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                  {STARTERS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => ask(s)}
                      className="rounded-lg border border-zinc-200 px-4 py-3 text-left text-sm hover:border-teal-400 hover:bg-teal-50 dark:border-zinc-800 dark:hover:bg-teal-950"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-teal-700 px-4 py-2 text-white">{m.text}</p>
                </div>
              ) : (
                <div key={m.id} className="max-w-[95%]">
                  {m.status === "searching" && <p className="animate-pulse text-zinc-500">Searching the textbook…</p>}
                  {m.status === "streaming" && Object.keys(m.segments).length === 0 && (
                    <p className="animate-pulse text-zinc-500">Reading {m.sources.length} passages…</p>
                  )}
                  {m.status !== "out_of_scope" && (
                    <Answer
                      segments={Object.keys(m.segments)
                        .map(Number)
                        .sort((a, b) => a - b)
                        .map((k) => m.segments[k])}
                      onCite={(citation) => setActive({ msgId: m.id, citation })}
                    />
                  )}
                  {m.notice && (
                    <p
                      className={
                        m.status === "error"
                          ? "mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-100"
                          : "rounded-lg bg-zinc-100 px-3 py-2 dark:bg-zinc-900"
                      }
                    >
                      {m.notice}
                    </p>
                  )}
                  {m.status === "done" && m.uncited && (
                    <p className="mt-2 text-xs text-zinc-500">No passages were cited in this answer.</p>
                  )}
                  {m.status === "done" && m.truncated && (
                    <p className="mt-2 text-xs text-zinc-500">The answer was cut off because it hit the length limit.</p>
                  )}
                  {m.status === "done" && m.sources.length > 0 && (
                    <details className="mt-3 text-sm text-zinc-500">
                      <summary className="cursor-pointer select-none">{m.sources.length} passages searched</summary>
                      <ol className="mt-2 space-y-1">
                        {m.sources.map((s) => (
                          <li key={s.id}>
                            <button
                              type="button"
                              className="text-left hover:text-teal-700 hover:underline"
                              onClick={() =>
                                setActive({
                                  msgId: m.id,
                                  citation: { source_index: s.index, start_block: 0, end_block: 0, cited_text: "" },
                                })
                              }
                            >
                              [{s.index + 1}] {s.section} {s.section_title}
                              {s.heading ? `: ${s.heading}` : ""} (p. {s.page_start})
                            </button>
                          </li>
                        ))}
                      </ol>
                    </details>
                  )}
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <form
          className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-800"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <div className="mx-auto flex max-w-3xl gap-2">
            <label htmlFor="question" className="sr-only">
              Your question
            </label>
            <textarea
              id="question"
              rows={1}
              value={input}
              maxLength={MAX_CHARS}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(input);
                }
              }}
              placeholder="Ask about human anatomy or physiology…"
              className="min-h-11 flex-1 resize-none rounded-lg border border-zinc-300 bg-white px-3 py-2 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
            {busy ? (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="rounded-lg border border-zinc-300 px-4 font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="rounded-lg bg-teal-700 px-4 font-medium text-white hover:bg-teal-800 disabled:opacity-40"
              >
                Ask
              </button>
            )}
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-zinc-500">
            For learning only. This is not medical advice; for health concerns, talk to a clinician.
          </p>
        </form>
      </div>

      {activeMsg && active && (
        <SourcePanel sources={activeMsg.sources} active={active.citation} onClose={() => setActive(null)} />
      )}
    </div>
  );
}
