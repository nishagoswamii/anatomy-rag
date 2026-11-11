"""Split the OpenStax PDF into sections using its outline (bookmarks).

Only explanatory prose is kept: each chapter's introduction and its numbered
sections (e.g. "22.2 The Lungs"). End-of-chapter material (key terms, review
questions), front matter, references, and the index are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from ingest.clean import printed_page_number

CHAPTER_RE = re.compile(r"^Chapter (\d+) (.+)$")
SECTION_RE = re.compile(r"^(\d+)\.(\d+) (.+)$")

# PDF index minus this offset gives the printed page number. Used only when a
# page has no readable footer (e.g. full-page figures).
DEFAULT_PAGE_OFFSET = 15


@dataclass
class Line:
    text: str
    pdf_page: int  # 0-based index into the PDF
    page: int  # printed page number


@dataclass
class Section:
    chapter: int
    chapter_title: str
    section: str  # "22.2", or "22.0" for the chapter introduction
    title: str
    lines: list[Line] = field(default_factory=list)


@dataclass
class _TocEntry:
    level: int
    pdf_page: int
    title: str


def _read_toc(pdf: pdfium.PdfDocument) -> list[_TocEntry]:
    entries = []
    for bm in pdf.get_toc(max_depth=2):
        dest = bm.get_dest()
        if dest is None:
            continue
        entries.append(_TocEntry(bm.level, dest.get_index(), bm.get_title().strip()))
    return entries


def _page_lines(pdf: pdfium.PdfDocument, index: int) -> list[str]:
    page = pdf[index]
    text = page.get_textpage().get_text_bounded()
    page.close()
    return text.splitlines()


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _find_line(lines: list[Line], start: int, pdf_page: int, prefix: str) -> int:
    """Index of the first line at/after `pdf_page` whose text starts with `prefix`.

    Falls back to the first line of `pdf_page` when the heading text can't be
    matched (the outline page is still a good approximation).
    """
    prefix = _norm(prefix)
    first_on_page = None
    for i in range(start, len(lines)):
        if lines[i].pdf_page < pdf_page:
            continue
        if first_on_page is None:
            first_on_page = i
        if lines[i].pdf_page > pdf_page + 1:
            break
        if _norm(lines[i].text).startswith(prefix):
            return i
    return first_on_page if first_on_page is not None else len(lines)


def extract_sections(pdf_path: Path) -> list[Section]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    toc = _read_toc(pdf)

    chapters = [(i, e) for i, e in enumerate(toc) if e.level == 0 and CHAPTER_RE.match(e.title)]
    sections: list[Section] = []

    for toc_i, chap in chapters:
        chap_num, chap_title = CHAPTER_RE.match(chap.title).groups()
        # Chapter ends where the next top-level outline entry starts.
        next_top = next(e for e in toc[toc_i + 1 :] if e.level == 0)
        end_page = next_top.pdf_page

        lines: list[Line] = []
        for p in range(chap.pdf_page, end_page):
            raw = _page_lines(pdf, p)
            page_no = printed_page_number(raw) or (p - DEFAULT_PAGE_OFFSET)
            lines.extend(Line(t, p, page_no) for t in raw)

        # Children are the level-1 entries up to the next top-level entry. (The
        # book's "References" entry repeats section titles, so it must not leak in.)
        children = []
        for e in toc[toc_i + 1 :]:
            if e.level == 0:
                break
            if e.level == 1:
                children.append(e)

        # Locate the start line of every child entry, in order.
        starts: list[tuple[_TocEntry, int]] = []
        cursor = 0
        for entry in children:
            m = SECTION_RE.match(entry.title)
            if m:
                prefix = f"{m.group(1)}.{m.group(2)} {m.group(3).split()[0]}"
            elif entry.title in ("Chapter Objectives", "Introduction"):
                continue  # the introduction runs from the chapter start
            else:
                prefix = entry.title
            idx = _find_line(lines, cursor, entry.pdf_page, prefix)
            starts.append((entry, idx))
            cursor = idx

        intro_end = starts[0][1] if starts else len(lines)
        sections.append(
            Section(int(chap_num), chap_title, f"{chap_num}.0", "Introduction", lines[:intro_end])
        )
        for k, (entry, idx) in enumerate(starts):
            m = SECTION_RE.match(entry.title)
            if not m:
                continue  # Key Terms, Chapter Review, questions...
            end = starts[k + 1][1] if k + 1 < len(starts) else len(lines)
            sections.append(
                Section(
                    int(chap_num),
                    chap_title,
                    f"{m.group(1)}.{m.group(2)}",
                    m.group(3),
                    lines[idx:end],
                )
            )
    pdf.close()
    return sections
