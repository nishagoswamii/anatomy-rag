"""Build data/chunks.jsonl from the OpenStax PDF.

uv run python -m ingest.run ../data/raw/ap2e.pdf ../data/chunks.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from ingest.chunk import chunk_section
from ingest.extract import extract_sections


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    sections = extract_sections(args.pdf)
    chunks = [c for s in sections for c in chunk_section(s)]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for c in chunks:
            f.write(json.dumps(c.to_json(), ensure_ascii=False) + "\n")

    words = [len(c.text.split()) for c in chunks]
    print(f"sections: {len(sections)}  chunks: {len(chunks)}")
    print(
        f"words/chunk: median {statistics.median(words):.0f}, "
        f"min {min(words)}, max {max(words)}, total {sum(words):,}"
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
