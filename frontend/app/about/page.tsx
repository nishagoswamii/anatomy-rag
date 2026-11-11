import type { Metadata } from "next";

export const metadata: Metadata = { title: "How it works · AnatomyRAG" };

const steps = [
  {
    title: "Ingest",
    body: "The 1,347-page PDF is split by its outline into 197 sections (each chapter's introduction and numbered sections), cleaned of page furniture, and cut into 2,112 chunks of about 350 tokens. Each chunk keeps its chapter, section, subheading, and printed page numbers, and is stored as 2-3 sentence blocks so citations can point at exact sentences.",
  },
  {
    title: "Retrieve",
    body: "The question is embedded with bge-small-en-v1.5 and matched against the chunks in LanceDB. A follow-up question is first rewritten into a standalone query.",
  },
  {
    title: "Gate",
    body: "A cross-encoder (ms-marco-MiniLM-L-6-v2) scores the retrieved passages against the question. If nothing scores above the threshold, the app answers \"not in this book\" without calling the language model at all.",
  },
  {
    title: "Answer",
    body: "Claude receives the passages as search-result blocks with citations enabled, plus a system prompt that limits it to those passages and to educational (not personal medical) information. The API returns structured citations, which become the numbered chips you can click.",
  },
];

export default function About() {
  return (
    <div className="overflow-y-auto px-4 py-10">
      <article className="mx-auto max-w-3xl space-y-8 leading-relaxed">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">How it works</h1>
          <p className="mt-3 text-zinc-600 dark:text-zinc-400">
            AnatomyRAG answers questions using only the OpenStax textbook <em>Anatomy and Physiology 2e</em>.
            Every claim links to the passage it came from, and questions the book doesn&apos;t cover are
            declined rather than answered from general knowledge.
          </p>
        </header>

        <ol className="space-y-5">
          {steps.map((s, i) => (
            <li key={s.title} className="flex gap-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-100 font-semibold text-teal-800 dark:bg-teal-900 dark:text-teal-100">
                {i + 1}
              </span>
              <div>
                <h2 className="font-semibold">{s.title}</h2>
                <p className="text-zinc-700 dark:text-zinc-300">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>

        <section>
          <h2 className="text-xl font-semibold">What the evals showed</h2>
          <p className="mt-2 text-zinc-700 dark:text-zinc-300">
            On 45 hand-checked questions, plain vector search put a passage from the right section first 91% of
            the time and in the top 3 every time. Adding BM25 keyword search and reranking the whole candidate
            list did not improve ranking on this book and added over 2 seconds per question, so the cross-encoder
            is used only as the relevance gate. As a gate it cleanly separates answerable questions from
            off-topic ones on the eval set. Full tables are in the repository&apos;s <code>evals/results</code>.
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Limits</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-700 dark:text-zinc-300">
            <li>Figures aren&apos;t searchable; only text and descriptive figure captions are indexed.</li>
            <li>Tables are flattened into text, so table-heavy passages read awkwardly.</li>
            <li>The gate is tuned on a small eval set and can still misjudge borderline questions.</li>
            <li>This is a study aid, not a source of medical advice.</li>
          </ul>
        </section>

        <p className="text-sm text-zinc-500">
          Textbook content: <em>Anatomy and Physiology 2e</em>, © Rice University (OpenStax), licensed under
          CC BY-NC-SA 4.0. Access for free at openstax.org. This project is non-commercial and not affiliated
          with OpenStax.
        </p>
      </article>
    </div>
  );
}
