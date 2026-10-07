import re

from app.agents.schemas import Source

CITATION_RE = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")


def cited_ids(answer: str) -> list[str]:
    """Source ids in order of first appearance. Handles [S1] and [S1, S2]."""
    seen: list[str] = []
    for match in CITATION_RE.finditer(answer):
        for sid in re.split(r"\s*,\s*", match.group(1)):
            if sid not in seen:
                seen.append(sid)
    return seen


def resolve(answer: str, sources: list[Source]) -> tuple[list[Source], list[str]]:
    """Split cited ids into known sources and ids the model invented."""
    by_id = {s.id: s for s in sources}
    ids = cited_ids(answer)
    return [by_id[i] for i in ids if i in by_id], [i for i in ids if i not in by_id]


def format_sources(sources: list[Source]) -> str:
    parts = []
    for s in sources:
        page = f"{s.page_index}" + (f" (printed {s.printed_label})" if s.printed_label else "")
        attrs = {
            "id": s.id,
            "doc": s.document_title,
            "type": s.doc_type if s.doc_type != "other" else None,
            "ref": s.reference_no,
            "issued": s.issued_on,
            "page": page,
        }
        tag = " ".join(f'{key}="{value.replace(chr(34), chr(39))}"' for key, value in attrs.items() if value)
        parts.append(f"<source {tag}>\n{s.content}\n</source>")
    return "\n\n".join(parts)
