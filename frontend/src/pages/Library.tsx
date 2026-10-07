import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { FileText, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { LazyPdfViewer as PdfViewer, type ViewerTarget } from '../components/LazyPdfViewer'
import { DocTypePill, EmptyState, ErrorNote, Input, LabelPill, Spinner } from '../components/ui'
import { get } from '../lib/api'
import { DOC_TYPES, formatIssued } from '../lib/docTypes'
import type { DocType, DocumentRow } from '../lib/types'

type Sort = 'issued' | 'added' | 'title'

const SORTS: { value: Sort; label: string }[] = [
  { value: 'issued', label: 'Newest issued' },
  { value: 'added', label: 'Recently added' },
  { value: 'title', label: 'Title A–Z' },
]

function compare(sort: Sort) {
  return (a: DocumentRow, b: DocumentRow) => {
    if (sort === 'title') return a.title.localeCompare(b.title)
    if (sort === 'issued' && (a.issued_on || b.issued_on)) {
      // Documents without an issue date go last.
      return (b.issued_on ?? '').localeCompare(a.issued_on ?? '')
    }
    return b.created_at.localeCompare(a.created_at)
  }
}

export function Library() {
  const { me } = useAuth()
  const labels = me?.labels ?? []
  const labelById = new Map(labels.map((l) => [l.id, l]))
  const [labelFilter, setLabelFilter] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<DocType | null>(null)
  const [sort, setSort] = useState<Sort>('issued')
  const [search, setSearch] = useState('')
  const [viewer, setViewer] = useState<ViewerTarget | null>(null)

  const docs = useQuery({
    queryKey: ['documents', 'ready'],
    queryFn: () => get<DocumentRow[]>('/documents?status=ready'),
  })

  const presentTypes = useMemo(() => new Set((docs.data ?? []).map((d) => d.doc_type)), [docs.data])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (docs.data ?? [])
      .filter(
        (d) =>
          (!labelFilter || d.label_ids.includes(labelFilter)) &&
          (!typeFilter || d.doc_type === typeFilter) &&
          (!q || d.title.toLowerCase().includes(q) || (d.reference_no ?? '').toLowerCase().includes(q)),
      )
      .sort(compare(sort))
  }, [docs.data, labelFilter, typeFilter, search, sort])

  return (
    <div className="flex h-full">
      <section className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-4 p-6">
          <div>
            <h1 className="text-lg font-semibold">Document library</h1>
            <p className="text-sm text-slate-500">
              Policies, SOPs, circulars, guidelines, reports and minutes in the collections you have access to.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative w-72 max-w-full">
                <Search className="absolute left-2.5 top-2 size-4 text-slate-400" />
                <Input
                  className="pl-8"
                  placeholder="Filter by title or reference no."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as Sort)}
                className="rounded-md border border-slate-300 bg-surface px-2 py-1.5 text-sm"
                aria-label="Sort documents"
              >
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-20 text-xs font-medium uppercase tracking-wide text-slate-400">Type</span>
              <FilterChip on={!typeFilter} onClick={() => setTypeFilter(null)}>
                All types
              </FilterChip>
              {DOC_TYPES.filter((t) => presentTypes.has(t.value)).map((t) => (
                <FilterChip key={t.value} on={typeFilter === t.value} onClick={() => setTypeFilter(t.value)}>
                  {t.label}
                </FilterChip>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-20 text-xs font-medium uppercase tracking-wide text-slate-400">Collection</span>
              <FilterChip on={!labelFilter} onClick={() => setLabelFilter(null)}>
                All collections
              </FilterChip>
              {labels.map((l) => (
                <button
                  key={l.id}
                  onClick={() => setLabelFilter(l.id)}
                  className={clsx('rounded-full', labelFilter === l.id && 'ring-2 ring-offset-1')}
                >
                  <LabelPill name={l.name} color={l.color} />
                </button>
              ))}
            </div>
          </div>

          {docs.isLoading && <Spinner className="mx-auto mt-10" />}
          <ErrorNote error={docs.error} />
          {docs.data && filtered.length === 0 && (
            <EmptyState title="No documents found">
              {docs.data.length ? 'Try another type, collection or search term.' : 'No documents have been published to your collections yet.'}
            </EmptyState>
          )}

          {filtered.length > 0 && (
            <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-surface">
              {filtered.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => setViewer({ documentId: d.id, page: 1, title: d.title })}
                    className={clsx(
                      'flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50',
                      viewer?.documentId === d.id && 'bg-indigo-50/50',
                    )}
                  >
                    <FileText className="size-5 shrink-0 text-slate-400" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <DocTypePill type={d.doc_type} />
                        <p className="truncate text-sm font-medium">{d.title}</p>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {[
                          d.reference_no,
                          d.issued_on && `issued ${formatIssued(d.issued_on)}`,
                          `${d.page_count} pages`,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                    <div className="flex flex-wrap justify-end gap-1">
                      {d.label_ids.map((id) => {
                        const l = labelById.get(id)
                        return l ? <LabelPill key={id} name={l.name} color={l.color} /> : null
                      })}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      {viewer && (
        <div className="w-[45%] min-w-[340px] shrink-0">
          <PdfViewer target={viewer} onClose={() => setViewer(null)} />
        </div>
      )}
    </div>
  )
}

function FilterChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'rounded-full px-2.5 py-1 text-xs font-medium',
        on ? 'bg-slate-800 text-white dark:bg-indigo-600' : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
      )}
    >
      {children}
    </button>
  )
}
