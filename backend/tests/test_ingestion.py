from app.ingestion.chunk import embedding_text, split_page
from app.ingestion.extract import detect_boilerplate, extract_pages, open_pdf


def test_page_index_follows_physical_order_not_printed_labels(report_pdf):
    reader = open_pdf(report_pdf)
    pages = extract_pages(reader, 0, len(reader.pages))

    assert [p.page_index for p in pages] == [1, 2, 3, 4, 5, 6]
    # Front matter is labelled i, ii and the body restarts at 1, so printed
    # labels disagree with the physical position and are kept for display only.
    assert [p.printed_label for p in pages] == ["i", "ii", "1", "2", "3", "4"]
    assert "Revenue grew 12%" in pages[2].text


def test_printed_label_dropped_when_it_matches_position():
    from tests.conftest import make_pdf

    reader = open_pdf(make_pdf([["a"], ["b"]]))
    assert [p.printed_label for p in extract_pages(reader, 0, 2)] == [None, None]


def test_batches_cover_every_page_exactly_once(report_pdf):
    reader = open_pdf(report_pdf)
    boilerplate = detect_boilerplate(reader)
    seen = []
    for start in range(0, len(reader.pages), 4):
        seen += [p.page_index for p in extract_pages(reader, start, start + 4, boilerplate)]
    assert seen == list(range(1, len(reader.pages) + 1))


def test_repeated_header_and_footer_are_removed(report_pdf):
    reader = open_pdf(report_pdf)
    pages = extract_pages(reader, 0, len(reader.pages))
    for p in pages:
        assert "CONFIDENTIAL" not in p.text
        assert "Page " not in p.text


def test_hyphenated_line_breaks_are_rejoined(report_pdf):
    reader = open_pdf(report_pdf)
    outlook = extract_pages(reader, 3, 4)[0]
    assert "pressure through 2024" in outlook.text


def test_blank_page_is_empty(report_pdf):
    reader = open_pdf(report_pdf)
    assert extract_pages(reader, 4, 5)[0].text == ""


def test_short_page_is_a_single_chunk():
    assert split_page("One page of text.", 6000, 600) == ["One page of text."]
    assert split_page("   ", 6000, 600) == []


def test_long_page_splits_with_overlap_and_covers_text():
    text = " ".join(f"Sentence number {i} about margins." for i in range(400))
    chunks = split_page(text, 1000, 100)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert chunks[0].startswith("Sentence number 0")
    assert chunks[-1].endswith("Sentence number 399 about margins.")
    # consecutive chunks overlap
    assert chunks[0][-40:].split()[-1] in chunks[1]


def test_embedding_text_carries_source():
    assert embedding_text("Q3 Outlook", 7, "body").startswith("Q3 Outlook — p.7\n")
