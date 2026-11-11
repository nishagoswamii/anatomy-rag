"use client";

import type { Citation, Source } from "@/lib/api";

function pages(s: Source) {
  return s.page_start === s.page_end ? `p. ${s.page_start}` : `pp. ${s.page_start}-${s.page_end}`;
}

export function SourcePanel({
  sources,
  active,
  onClose,
}: {
  sources: Source[];
  active: Citation | null;
  onClose: () => void;
}) {
  const source = active ? sources[active.source_index] : null;
  if (!source || !active) return null;

  return (
    <aside
      aria-label="Source passage"
      className="fixed inset-x-0 bottom-0 z-20 max-h-[70vh] overflow-y-auto border-t border-zinc-200 bg-white p-5 shadow-2xl lg:static lg:inset-auto lg:z-auto lg:max-h-none lg:w-[26rem] lg:shrink-0 lg:border-l lg:border-t-0 lg:shadow-none dark:border-zinc-800 dark:bg-zinc-950"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-300">
            Source {active.source_index + 1} · Chapter {source.chapter}
          </p>
          <h2 className="mt-1 font-semibold">
            {source.section} {source.section_title}
          </h2>
          {source.heading && <p className="text-sm text-zinc-600 dark:text-zinc-400">{source.heading}</p>}
          <p className="mt-1 text-sm text-zinc-500">{pages(source)}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 py-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          aria-label="Close source"
        >
          ✕
        </button>
      </div>

      <div className="space-y-2 text-sm leading-relaxed">
        {source.blocks.map((block, i) => {
          const cited = i >= active.start_block && i < active.end_block;
          return (
            <p
              key={i}
              className={
                cited
                  ? "rounded bg-amber-100 px-2 py-1 text-zinc-900 dark:bg-amber-900/40 dark:text-amber-50"
                  : "px-2 text-zinc-600 dark:text-zinc-400"
              }
            >
              {block}
            </p>
          );
        })}
      </div>

      <div className="mt-5 border-t border-zinc-200 pt-3 text-xs text-zinc-500 dark:border-zinc-800">
        <a href={source.url} target="_blank" rel="noreferrer" className="font-medium text-teal-700 underline dark:text-teal-300">
          Read this section on OpenStax ↗
        </a>
        <p className="mt-2">
          From <em>Anatomy and Physiology 2e</em> by OpenStax, CC BY-NC-SA 4.0. Access for free at
          openstax.org.
        </p>
      </div>
    </aside>
  );
}
