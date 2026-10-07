import type { DocType } from './types'

export const DOC_TYPES: { value: DocType; label: string; color: string }[] = [
  { value: 'policy', label: 'Policy', color: '#2563eb' },
  { value: 'sop', label: 'SOP', color: '#0891b2' },
  { value: 'circular', label: 'Circular', color: '#7c3aed' },
  { value: 'guideline', label: 'Guideline', color: '#16a34a' },
  { value: 'report', label: 'Report', color: '#d97706' },
  { value: 'minutes', label: 'Minutes', color: '#db2777' },
  { value: 'other', label: 'Other', color: '#475569' },
]

const byValue = new Map(DOC_TYPES.map((t) => [t.value, t]))

export const docTypeInfo = (value: string | null | undefined) => byValue.get((value ?? 'other') as DocType) ?? DOC_TYPES[6]

/** "12 Mar 2024" for an ISO date (YYYY-MM-DD), read as a calendar date with no timezone shift. */
export function formatIssued(date: string | null | undefined): string | null {
  if (!date) return null
  const [y, m, d] = date.split('-').map(Number)
  if (!y || !m || !d) return date
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}
