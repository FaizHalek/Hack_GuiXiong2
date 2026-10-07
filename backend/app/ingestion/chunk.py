"""Page-level chunking.

One chunk per page by default, so a citation always resolves to exactly one
physical page. Very long pages are split into overlapping sub-chunks that keep
the same page_index.
"""

import re


def split_page(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            # Prefer to break on a paragraph, then a sentence, then a space.
            for pattern in (r"\n\n", r"[.!?]\s", r"\s"):
                matches = list(re.finditer(pattern, window))
                if matches and matches[-1].end() > max_chars // 2:
                    end = start + matches[-1].end()
                    break
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        # Start the overlap on a word boundary so no chunk begins mid-word.
        start = max(end - overlap, start + 1)
        if start < end and not text[start - 1].isspace():
            space = text.find(" ", start, end)
            start = space + 1 if space != -1 else start
    return [c for c in chunks if c]


def embedding_text(document_title: str, page_index: int, content: str) -> str:
    """Prefix chunk text with its source so the embedding carries that context."""
    return f"{document_title} — p.{page_index}\n{content}"
