"""Line-level cleanup of extracted PDF text.

Turns the raw lines of a section into a sequence of items: subheadings,
figure captions, and runs of body text. Page furniture (running headers,
footers, attribution lines) and learning-objective lists are removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FOOTER_ATTRIBUTION = "access for free at openstax.org"
# "8 1 • An Introduction to the Human Body" (even pages, number first)
EVEN_HEADER_RE = re.compile(r"^(\d+) \d+ • .+$")
# "1.2 • Structural Organization of the Human Body 9" (odd pages, number last)
ODD_HEADER_RE = re.compile(r"^\d+(?:\.\d+)? • .+? (\d+)$")
CAPTION_RE = re.compile(r"^(FIGURE|TABLE) (\d+\.\d+)\s*(.*)$")
CREDIT_RE = re.compile(r"\s*\(credit[^()]*(?:\([^()]*\)[^()]*)*\)", re.IGNORECASE)
TERMINAL = (".", "?", "!", ":", ")", "”", '"')

ItemKind = Literal["heading", "caption", "text"]


@dataclass
class Item:
    kind: ItemKind
    text: str
    page: int
    # For text items: (offset, page) pairs marking where each source line starts,
    # so sentences can be mapped back to the page they begin on.
    line_starts: list[tuple[int, int]] | None = None


def normalize(s: str) -> str:
    s = s.replace("\x02", "-").replace("­", "")
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", "", s)
    return s.strip()


def is_page_furniture(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.lower() == FOOTER_ATTRIBUTION:
        return True
    return bool(EVEN_HEADER_RE.match(s) or ODD_HEADER_RE.match(s))


def printed_page_number(raw_lines: list[str]) -> int | None:
    """Read the printed page number from a page's running header/footer."""
    candidates = [line.strip() for line in raw_lines[-4:] + raw_lines[:2]]
    for s in candidates:
        if m := EVEN_HEADER_RE.match(s):
            return int(m.group(1))
        if m := ODD_HEADER_RE.match(s):
            return int(m.group(1))
    return None


def _is_all_caps_label(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters) and len(s) <= 60


_DANGLING = {"and", "or", "of", "the", "to", "in", "a", "an", "for", "with", "by", "on", "at"}


def _looks_like_heading(s: str, prev_ended_sentence: bool, next_line: str | None) -> bool:
    if not prev_ended_sentence or s.endswith(TERMINAL) or s.endswith(","):
        return False
    words = s.split()
    if not 1 <= len(words) <= 10 or not s[0].isupper():
        return False
    if words[-1].lower() in _DANGLING:
        return False  # a wrapped phrase or table cell, not a heading
    if next_line and next_line[0].islower():
        return False  # the line continues onto the next one
    if CAPTION_RE.match(s) or s.startswith("•"):
        return False
    if sum(c.isdigit() for c in s) > len(s) / 4:
        return False  # table rows
    long_words = [w for w in words if len(w) >= 4]
    capitalized = [w for w in long_words if w[0].isupper()]
    return not long_words or len(capitalized) >= len(long_words) / 2


def clean_lines(lines: list[tuple[str, int]], drop_titles: set[str] | None = None) -> list[Item]:
    """Convert (text, printed_page) lines into headings, captions and text runs."""
    drop = {t.lower() for t in (drop_titles or set())}
    items: list[Item] = []
    run_parts: list[str] = []
    run_starts: list[tuple[int, int]] = []
    run_len = 0

    def flush_run():
        nonlocal run_parts, run_starts, run_len
        if run_parts:
            text = "".join(run_parts).strip()
            if text:
                items.append(Item("text", text, run_starts[0][1], run_starts))
        run_parts, run_starts, run_len = [], [], 0

    def append_text(s: str, page: int):
        nonlocal run_len
        if run_parts and run_parts[-1].endswith("-") and s[:1].islower():
            pass  # hyphenated word wrapped across lines: join without a space
        elif run_parts:
            run_parts.append(" ")
            run_len += 1
        run_starts.append((run_len, page))
        run_parts.append(s)
        run_len += len(s)

    in_objectives = False
    caption: list[str] | None = None
    caption_page = 0
    prev_ended_sentence = True

    kept = [(normalize(raw), page) for raw, page in lines if not is_page_furniture(raw)]
    kept = [(s, page) for s, page in kept if s]

    for i, (s, page) in enumerate(kept):
        next_line = kept[i + 1][0] if i + 1 < len(kept) else None
        low = s.lower()

        if caption is not None:
            # A caption continues onto the next line only if its last line was
            # full-width (i.e. it wrapped) and hasn't finished.
            last = caption[-1]
            if len(caption) < 4 and len(last) >= 70 and not last.endswith((".", ")")):
                caption.append(s)
                continue
            _emit_caption(items, caption, caption_page)
            caption = None

        if low in ("learning objectives", "chapter objectives"):
            flush_run()
            in_objectives = True
            continue
        if in_objectives:
            if (
                s.startswith("•")
                or s[0].islower()
                or low.startswith(("by the end of this section", "after studying this chapter"))
            ):
                continue
            in_objectives = False

        if low in drop or re.fullmatch(r"chapter \d+", low):
            continue
        if _is_all_caps_label(s):
            continue  # box labels: "INTERACTIVE LINK", "CAREER CONNECTION", ...

        if CAPTION_RE.match(s):
            flush_run()
            caption = [s]
            caption_page = page
            prev_ended_sentence = True
            continue

        if _looks_like_heading(s, prev_ended_sentence, next_line):
            flush_run()
            items.append(Item("heading", s, page))
            prev_ended_sentence = True
            continue

        if s.startswith("•"):
            s = s.lstrip("• ").strip()
            if run_parts and not "".join(run_parts).rstrip().endswith(TERMINAL):
                run_parts.append(";")
                run_len += 1
        append_text(s, page)
        prev_ended_sentence = s.endswith(TERMINAL)

    if caption is not None:
        _emit_caption(items, caption, caption_page)
    flush_run()
    return items


def _emit_caption(items: list[Item], parts: list[str], page: int) -> None:
    text = CREDIT_RE.sub("", " ".join(parts)).strip()
    m = CAPTION_RE.match(text)
    if not m:
        return
    kind, number, rest = m.groups()
    # Title-only captions ("FIGURE 22.13 Gross Anatomy of the Lungs") carry no
    # information without the image, so they are dropped.
    if len(rest.split()) <= 8 and not rest.endswith("."):
        return
    items.append(Item("caption", f"{kind.title()} {number}: {rest}", page))
