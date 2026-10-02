import { describe, expect, it } from 'vitest'
import { citationIdFromHref, escapeHtml, linkCitations, normaliseForMatch, runMatchesEvidence } from './citations'
import { createSseParser } from './sse'

describe('linkCitations', () => {
  it('links single and grouped citations', () => {
    expect(linkCitations('Up 12% [S1]. Down [S2, S3].')).toBe(
      'Up 12% [S1](#cite-S1). Down [S2](#cite-S2)[S3](#cite-S3).',
    )
  })
  it('leaves other brackets alone', () => {
    expect(linkCitations('See [note] and [1].')).toBe('See [note] and [1].')
  })
})

describe('citationIdFromHref', () => {
  it('extracts ids', () => {
    expect(citationIdFromHref('#cite-S12')).toBe('S12')
    expect(citationIdFromHref('https://example.com')).toBeNull()
  })
})

describe('evidence matching', () => {
  const evidence = normaliseForMatch('Revenue grew 12% year-on-year, driven by data-centre demand.')
  it('matches runs inside the quote', () => {
    expect(runMatchesEvidence('Revenue grew 12% year-on-year,', evidence)).toBe(true)
    expect(runMatchesEvidence('driven by data-centre', evidence)).toBe(true)
  })
  it('ignores short or unrelated runs', () => {
    expect(runMatchesEvidence('by', evidence)).toBe(false)
    expect(runMatchesEvidence('Margins fell sharply', evidence)).toBe(false)
  })
})

describe('escapeHtml', () => {
  it('escapes markup', () => {
    expect(escapeHtml('<b>&"')).toBe('&lt;b&gt;&amp;&quot;')
  })
})

describe('createSseParser', () => {
  it('handles events split across chunks', () => {
    const parse = createSseParser<{ type: string; text?: string }>()
    expect(parse('data: {"type":"delta","te')).toEqual([])
    expect(parse('xt":"hi"}\n\ndata: {"type":"evaluating"}\n\n')).toEqual([
      { type: 'delta', text: 'hi' },
      { type: 'evaluating' },
    ])
  })
})
