import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { FileText, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { LazyPdfViewer as PdfViewer, type ViewerTarget } from '../components/LazyPdfViewer'
import { EmptyState, ErrorNote, Input, LabelPill, Spinner } from '../components/ui'
import { get } from '../lib/api'
import type { DocumentRow } from '../lib/types'

export function Library() {
  const { me } = useAuth()
  const labels = me?.labels ?? []
  const labelById = new Map(labels.map((l) => [l.id, l]))
  const [labelFilter, setLabelFilter] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [viewer, setViewer] = useState<ViewerTarget | null>(null)

  const docs = useQuery({
    queryKey: ['documents', 'ready'],
    queryFn: () => get<DocumentRow[]>('/documents?status=ready'),
  })

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (docs.data ?? []).filter(
      (d) => (!labelFilter || d.label_ids.includes(labelFilter)) && (!q || d.title.toLowerCase().includes(q)),
    )
  }, [docs.data, labelFilter, search])

  return (
    <div className="flex h-full">
      <section className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-4 p-6">
          <div>
            <h1 className="text-lg font-semibold">Research library</h1>
            <p className="text-sm text-slate-500">Reports in the libraries you have access to.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-64">
              <Search className="absolute left-2.5 top-2 size-4 text-slate-400" />
              <Input className="pl-8" placeholder="Filter by title" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <button
              onClick={() => setLabelFilter(null)}
              className={clsx('rounded-full px-2.5 py-1 text-xs font-medium', !labelFilter ? 'bg-slate-800 text-white dark:bg-indigo-600' : 'bg-slate-100')}
            >
              All
            </button>
            {labels.map((l) => (
              <button key={l.id} onClick={() => setLabelFilter(l.id)} className={clsx(labelFilter === l.id && 'ring-2 ring-offset-1 rounded-full')}>
                <LabelPill name={l.name} color={l.color} />
              </button>
            ))}
          </div>

          {docs.isLoading && <Spinner className="mx-auto mt-10" />}
          <ErrorNote error={docs.error} />
          {docs.data && filtered.length === 0 && (
            <EmptyState title="No reports found">Try another library or search term.</EmptyState>
          )}

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
                    <p className="truncate text-sm font-medium">{d.title}</p>
                    <p className="text-xs text-slate-500">
                      {d.page_count} pages · added {new Date(d.created_at).toLocaleDateString()}
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
