from ingest.chunk import _split_long, chunk_section, section_slug, split_sentences
from ingest.clean import clean_lines, is_page_furniture, printed_page_number
from ingest.extract import Line, Section


def test_page_furniture_and_page_numbers():
    assert is_page_furniture("Access for free at openstax.org")
    assert is_page_furniture("8 1 • An Introduction to the Human Body")
    assert is_page_furniture("22.2 • The Lungs 985")
    assert not is_page_furniture("• Describe the overall function of the lung")
    assert printed_page_number(["text", "22.2 • The Lungs 985"]) == 985
    assert (
        printed_page_number(["text", "8 1 • An Introduction", "Access for free at openstax.org"])
        == 8
    )


def test_clean_drops_objectives_and_detects_headings():
    lines = [
        ("LEARNING OBJECTIVES", 1),
        ("By the end of this section, you will be able to:", 1),
        ("• Describe the overall function of the lung", 1),
        ("• Summarize the blood flow pattern associated with", 1),
        ("the lungs", 1),
        ("A major organ of the respiratory system, each lung houses structures.", 1),
        ("Gross Anatomy of the Lungs", 2),
        ("The lungs are pyramid-shaped, paired organs.", 2),
    ]
    items = clean_lines(lines)
    assert [(i.kind, i.text) for i in items] == [
        ("text", "A major organ of the respiratory system, each lung houses structures."),
        ("heading", "Gross Anatomy of the Lungs"),
        ("text", "The lungs are pyramid-shaped, paired organs."),
    ]
    assert items[2].page == 2


def test_table_cell_is_not_a_heading():
    lines = [("It branches.", 1), ("Brachiocephalic", 1), ("artery Single vessel on the right.", 1)]
    assert all(i.kind == "text" for i in clean_lines(lines))


def test_split_sentences_keeps_abbreviations():
    s = "Muscles (e.g. the biceps) contract. Bones store calcium. pH is 7.4 here."
    assert split_sentences(s) == [
        "Muscles (e.g. the biceps) contract.",
        "Bones store calcium.",
        "pH is 7.4 here.",
    ]


def test_split_long_breaks_run_on_table_text():
    run_on = "; ".join(f"vessel {i} supplies region {i}" for i in range(40))
    pieces = _split_long(run_on)
    assert len(pieces) > 1
    assert all(len(p.split()) <= 50 for p in pieces)
    assert " ".join(pieces).split() == run_on.split()


def test_section_slug():
    s = Section(22, "The Respiratory System", "22.2", "The Lungs")
    assert section_slug(s) == "22-2-the-lungs"
    assert section_slug(Section(1, "x", "1.0", "Introduction")) == "1-introduction"


def test_chunk_section_records_pages_and_blocks():
    sentences = [
        f"Sentence number {i} talks about the alveoli and gas exchange." for i in range(80)
    ]
    lines = [Line("22.4 Gas Exchange", 0, 999)] + [
        Line(s, 0, 999 if i < 40 else 1000) for i, s in enumerate(sentences)
    ]
    chunks = chunk_section(Section(22, "The Respiratory System", "22.4", "Gas Exchange", lines))
    assert len(chunks) >= 2
    assert chunks[0].id == "22.4-00"
    assert chunks[0].page_start == 999 and chunks[-1].page_end == 1000
    assert all(len(b.split()) <= 60 for c in chunks for b in c.blocks)
    assert chunks[0].url.endswith("/22-4-gas-exchange")
    assert "22.4 Gas Exchange" not in chunks[0].blocks[0]  # title line dropped
