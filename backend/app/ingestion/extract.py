"""Per-page PDF text extraction.

References are built from the *physical* page order in the file
(page_index = position + 1), never from the numbering printed on the page or
the PDF's page labels, which are often roman numerals, restart per section, or
are simply missing. The printed label is kept only so the viewer can show it.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader

BOILERPLATE_SAMPLE = 30
EDGE_LINES = 3  # only header/footer candidates: first/last N lines of a page


@dataclass
class PageText:
    page_index: int  # 1-based physical position in the PDF
    printed_label: str | None
    text: str


def open_pdf(data: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(data))


def _raw_text(reader: PdfReader, i: int) -> str:
    try:
        return reader.pages[i].extract_text() or ""
    except Exception:  # a single malformed page must not sink the whole document
        return ""


def _line_key(line: str) -> str:
    # "Page 3 of 80" and "Page 4 of 80" should count as the same footer.
    return re.sub(r"\d+", "#", line.strip().lower())


def _edge_lines(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[:EDGE_LINES] + lines[-EDGE_LINES:]


def detect_boilerplate(reader: PdfReader) -> set[str]:
    """Header/footer lines repeated on more than half of a sample of pages.

    The sample is deterministic so every ingestion batch strips the same lines.
    """
    n = len(reader.pages)
    if n < 4:
        return set()
    step = max(1, n // BOILERPLATE_SAMPLE)
    sample = list(range(0, n, step))[:BOILERPLATE_SAMPLE]
    counts: Counter[str] = Counter()
    for i in sample:
        counts.update({_line_key(ln) for ln in _edge_lines(_raw_text(reader, i))})
    threshold = len(sample) / 2
    return {key for key, c in counts.items() if c > threshold and key}


def normalise(text: str, boilerplate: set[str]) -> str:
    lines = text.splitlines()
    non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
    edges = set(non_empty[:EDGE_LINES] + non_empty[-EDGE_LINES:])
    kept = [ln for i, ln in enumerate(lines) if not (i in edges and _line_key(ln) in boilerplate)]
    text = "\n".join(kept)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def printed_labels(reader: PdfReader) -> list[str | None]:
    try:
        return list(reader.page_labels)
    except Exception:
        return [None] * len(reader.pages)


def extract_pages(reader: PdfReader, start: int, end: int, boilerplate: set[str] | None = None) -> list[PageText]:
    """Extract pages [start, end) using 0-based positions; returns 1-based page_index."""
    if boilerplate is None:
        boilerplate = detect_boilerplate(reader)
    labels = printed_labels(reader)
    out = []
    for i in range(start, min(end, len(reader.pages))):
        label = labels[i] if i < len(labels) else None
        out.append(
            PageText(
                page_index=i + 1,
                printed_label=label if label != str(i + 1) else None,
                text=normalise(_raw_text(reader, i), boilerplate),
            )
        )
    return out
