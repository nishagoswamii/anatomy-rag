export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Source = {
  index: number;
  id: string;
  chapter: number;
  chapter_title: string;
  section: string;
  section_title: string;
  heading: string | null;
  page_start: number;
  page_end: number;
  url: string;
  blocks: string[];
  score: number;
};

export type Citation = {
  source_index: number;
  start_block: number;
  end_block: number;
  cited_text: string;
};

export type ChatEvent =
  | { type: "sources"; sources: Source[]; query: string }
  | { type: "text"; block: number; text: string }
  | ({ type: "citation"; block: number } & Citation)
  | { type: "out_of_scope"; message: string }
  | { type: "reset" }
  | { type: "error"; code: string; message: string }
  | {
      type: "done";
      stop_reason: string;
      truncated?: boolean;
      uncited?: boolean;
      cost_usd?: number;
    };

export type HistoryTurn = { role: "user" | "assistant"; text: string };

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
  ) {
    super(message);
  }
}

/** POST a question and call `onEvent` for each server-sent event. */
export async function streamChat(
  question: string,
  history: HistoryTurn[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
    signal,
  });
  if (!res.ok || !res.body) {
    let message = "Something went wrong. Please try again.";
    let code = "http_" + res.status;
    try {
      const body = await res.json();
      if (body?.message) message = body.message;
      if (body?.error) code = body.error;
      else if (res.status === 422) message = "That request wasn't valid. Try rephrasing.";
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, code);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = raw
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as ChatEvent);
    }
  }
}

/** Resolves true once the backend answers its health check. */
export async function waitForBackend(signal?: AbortSignal): Promise<boolean> {
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      const res = await fetch(`${API_URL}/api/health`, { signal });
      if (res.ok) return true;
    } catch {
      if (signal?.aborted) return false;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  return false;
}
