import io

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_pdf(pages: list[list[str]], header: str = "ACME RESEARCH — CONFIDENTIAL", roman_front_matter: int = 0) -> bytes:
    """Build a PDF where each page has a repeated header, body lines and a 'Page N' footer.

    The first `roman_front_matter` pages get roman-numeral page labels and the
    rest restart at 1, like a real report with a preface.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    for n, lines in enumerate(pages, start=1):
        c.drawString(72, height - 50, header)
        y = height - 100
        for line in lines:
            c.drawString(72, y, line)
            y -= 16
        c.drawString(72, 40, f"Page {n} of {len(pages)}")
        c.showPage()
    c.save()

    if not roman_front_matter:
        return buf.getvalue()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    writer.set_page_label(0, roman_front_matter - 1, style="/r")
    writer.set_page_label(roman_front_matter, len(pages) - 1, style="/D", start=1)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def report_pdf() -> bytes:
    return make_pdf(
        [
            ["Preface", "This report covers the semiconductor market."],
            ["Table of contents"],
            ["Executive summary", "Revenue grew 12% year on year in 2023,", "driven by data-centre demand."],
            ["Outlook", "We expect margins to remain under pres-", "sure through 2024."],
            [],  # blank page, e.g. a scanned figure
            ["Appendix", "Methodology notes."],
        ],
        roman_front_matter=2,
    )
