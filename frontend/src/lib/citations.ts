const CITATION_RE = /\[(S\d+(?:\s*,\s*S\d+)*)\]/g

/**
 * Turn "[S1]" / "[S1, S2]" markers into markdown links (`#cite-S1`) so the
 * markdown renderer can swap them for clickable citation chips.
 */
export function linkCitations(answer: string): string {
  return answer.replace(CITATION_RE, (_, ids: string) =>
    ids
      .split(/\s*,\s*/)
      .map((id) => `[${id}](#cite-${id})`)
      .join(''),
  )
}

export function citationIdFromHref(href: string | undefined): string | null {
  const match = href?.match(/^#cite-(S\d+)$/)
  return match ? match[1] : null
}

/** Normalise text for loose matching between evidence quotes and PDF text runs. */
export function normaliseForMatch(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()
}

/**
 * Should a text run from the PDF text layer be highlighted for this evidence?
 * PDF text is split into arbitrary runs, so we highlight every run (of a
 * meaningful length) that appears inside the normalised evidence quote.
 */
export function runMatchesEvidence(run: string, normalisedEvidence: string): boolean {
  const n = normaliseForMatch(run)
  if (!normalisedEvidence || n.length < 4) return false
  return normalisedEvidence.includes(n) || (n.length > normalisedEvidence.length && n.includes(normalisedEvidence))
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
}
