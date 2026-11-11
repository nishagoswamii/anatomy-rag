"""Sentence-aware chunking.

Each chunk is ~350 tokens of one section, never crossing a section boundary,
and is stored as a list of small blocks (2-3 sentences). Claude cites whole
blocks of a search result, so small blocks give precise citations.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import asdict, dataclass

from ingest.clean import Item, clean_lines
from ingest.extract import Section

TARGET_WORDS = 260  # ~350 tokens
MIN_WORDS = 80  # don't start a new chunk at a heading before this size
BLOCK_MAX_WORDS = 60
BLOCK_MAX_SENTENCES = 3
BOOK_URL = "https://openstax.org/books/anatomy-and-physiology-2e/pages"

_ABBREVIATIONS = ("e.g.", "i.e.", "et al.", "vs.", "approx.", "Dr.", "Fig.", "ca.", "St.")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])[”\"]?\s+(?=[A-Z0-9“\"(]|pH\b)")
_URL_RE = re.compile(r"https?://|openstax\.org/l/|www\.", re.IGNORECASE)


@dataclass
class Sentence:
    text: str
    page: int
    heading: str | None


@dataclass
class Chunk:
    id: str
    chapter: int
    chapter_title: str
    section: str
    section_title: str
    heading: str | None
    page_start: int
    page_end: int
    url: str
    blocks: list[str]

    @property
    def text(self) -> str:
        return " ".join(self.blocks)

    def to_json(self) -> dict:
        return asdict(self)


def split_sentences(text: str) -> list[str]:
    protected = text
    for i, abbr in enumerate(_ABBREVIATIONS):
        protected = protected.replace(abbr, f"\x00{i}\x00")
    parts = _SENTENCE_END_RE.split(protected)
    out = []
    for p in parts:
        for i, abbr in enumerate(_ABBREVIATIONS):
            p = p.replace(f"\x00{i}\x00", abbr)
        p = p.strip()
        if p:
            out.append(p)
    return out


def _split_long(sentence: str, max_words: int = 80, piece_words: int = 50) -> list[str]:
    """Break run-on "sentences" (usually flattened tables) into citable pieces."""
    if _words(sentence) <= max_words:
        return [sentence]
    pieces: list[str] = []
    current: list[str] = []
    for part in re.split(r"(?<=;)\s+", sentence):
        words = part.split()
        while len(words) > piece_words:  # no semicolons to split on
            if current:
                pieces.append(" ".join(current))
                current = []
            pieces.append(" ".join(words[:piece_words]))
            words = words[piece_words:]
        if current and _words(" ".join(current)) + len(words) > piece_words:
            pieces.append(" ".join(current))
            current = []
        current.extend(words)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _sentences_with_pages(item: Item) -> list[tuple[str, int]]:
    offsets = [o for o, _ in item.line_starts]
    pages = [p for _, p in item.line_starts]
    result = []
    pos = 0
    for s in split_sentences(item.text):
        start = item.text.find(s, pos)
        if start < 0:
            start = pos
        pos = start + len(s)
        idx = max(bisect.bisect_right(offsets, start) - 1, 0)
        result.extend((piece, pages[idx]) for piece in _split_long(s))
    return result


def section_sentences(items: list[Item]) -> list[Sentence]:
    sentences: list[Sentence] = []
    heading: str | None = None
    for item in items:
        if item.kind == "heading":
            heading = item.text
            sentences.append(Sentence("", item.page, heading))  # heading marker
        elif item.kind == "caption":
            sentences.append(Sentence(item.text, item.page, heading))
        else:
            for text, page in _sentences_with_pages(item):
                if _URL_RE.search(text):
                    continue  # "Visit this site..." interactive-link boilerplate
                sentences.append(Sentence(text, page, heading))
    return sentences


def _words(s: str) -> int:
    return len(s.split())


def _to_blocks(sentences: list[Sentence]) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for s in sentences:
        if current and (
            len(current) >= BLOCK_MAX_SENTENCES
            or _words(" ".join(current)) + _words(s.text) > BLOCK_MAX_WORDS
        ):
            blocks.append(" ".join(current))
            current = []
        current.append(s.text)
    if current:
        blocks.append(" ".join(current))
    return blocks


def section_slug(section: Section) -> str:
    if section.section.endswith(".0"):
        return f"{section.chapter}-introduction"
    title = re.sub(r"[^a-z0-9]+", "-", section.title.lower()).strip("-")
    return f"{section.section.replace('.', '-')}-{title}"


def chunk_section(section: Section) -> list[Chunk]:
    lines = [(ln.text, ln.page) for ln in section.lines]
    # Drop the section's own title line(s); the title is stored as metadata.
    drop = {section.chapter_title, "Introduction"}
    if lines and not section.section.endswith(".0"):
        first = lines.pop(0)[0].strip()
        full = f"{section.section} {section.title}"
        if len(first) < len(full) and lines:
            lines.pop(0)  # title wrapped onto a second line
    sentences = section_sentences(clean_lines(lines, drop_titles=drop))

    groups: list[list[Sentence]] = []
    current: list[Sentence] = []
    count = 0
    for s in sentences:
        is_heading_marker = s.text == ""
        if is_heading_marker:
            if count >= MIN_WORDS:
                groups.append(current)
                current, count = [], 0
            continue
        if count + _words(s.text) > TARGET_WORDS and count >= MIN_WORDS:
            groups.append(current)
            # one-sentence overlap, but only within the same subheading
            current = [current[-1]] if current[-1].heading == s.heading else []
            count = sum(_words(x.text) for x in current)
        current.append(s)
        count += _words(s.text)
    if current:
        if groups and count < MIN_WORDS / 2 and groups[-1][-1].heading == current[-1].heading:
            groups[-1].extend(x for x in current if x not in groups[-1])
        else:
            groups.append(current)

    url = f"{BOOK_URL}/{section_slug(section)}"
    chunks = []
    for k, group in enumerate(groups):
        if not group:
            continue
        chunks.append(
            Chunk(
                id=f"{section.section}-{k:02d}",
                chapter=section.chapter,
                chapter_title=section.chapter_title,
                section=section.section,
                section_title=section.title,
                heading=group[0].heading,
                page_start=min(s.page for s in group),
                page_end=max(s.page for s in group),
                url=url,
                blocks=_to_blocks(group),
            )
        )
    return chunks
