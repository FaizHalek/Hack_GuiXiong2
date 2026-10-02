from typing import Literal

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    """Output of the Query Agent."""

    needs_retrieval: bool = Field(description="False only for greetings or questions about the assistant itself.")
    standalone_question: str = Field(description="The user's question rewritten to be understandable without the chat history.")
    sub_queries: list[str] = Field(description="1-3 focused search queries that together cover the question.")
    keywords: list[str] = Field(default_factory=list, description="Distinctive names, tickers or phrases for keyword search.")
    direct_reply: str = Field(default="", description="Reply text when needs_retrieval is false; otherwise empty.")


class ClaimCheck(BaseModel):
    claim: str
    source_ids: list[str] = Field(default_factory=list, description="Source ids cited for this claim, e.g. ['S1'].")
    verdict: Literal["supported", "partial", "unsupported"]
    citation_correct: bool = Field(default=False, description="True if the cited source(s) actually contain the support.")
    evidence_quote: str = Field(default="", description="Short verbatim quote from the cited source supporting the claim.")
    note: str = Field(default="", description="One short sentence explaining any problem; empty if supported.")


class Evaluation(BaseModel):
    """Output of the Evaluator Agent."""

    claims: list[ClaimCheck]
    grounded_score: float = Field(description="0-1: share of the answer's factual content supported by its citations.")
    summary: str = Field(default="", description="One sentence overall assessment.")


class Source(BaseModel):
    id: str  # "S1"
    chunk_id: str
    document_id: str
    document_title: str
    page_index: int
    printed_label: str | None = None
    content: str
    score: float = 0.0

    def public(self, snippet: str | None = None) -> dict:
        return {
            "id": self.id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "page_index": self.page_index,
            "printed_label": self.printed_label,
            "snippet": snippet or self.content[:300],
        }


Verdict = Literal["grounded", "partial", "low_confidence", "no_sources", "not_applicable"]
