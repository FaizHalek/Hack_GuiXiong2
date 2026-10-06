import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button, Card, EmptyState, ErrorNote, Spinner } from '../../components/ui'
import { del, get, post, put } from '../../lib/api'
import { STORAGE_BUCKET, supabase } from '../../lib/supabase'
import type { DocumentRow, Label } from '../../lib/types'
import { LabelToggles } from './LabelToggles'

type AdminDocument = DocumentRow & { empty_pages: number }

interface UploadJob {
  key: string
  name: string
  phase: 'registering' | 'uploading' | 'ingesting' | 'done' | 'error'
  pagesDone: number
  pageCount: number | null
  error?: string
}

interface IngestBatch {
  next_start: number
  page_count: number
  done: boolean
}

/** Drive batched ingestion until the backend reports the document is done. */
async function runIngestion(documentId: string, start: number, onProgress: (done: number, total: number) => void) {
  let next = start
  for (;;) {
    const batch = await post<IngestBatch>(`/admin/documents/${documentId}/ingest?start=${next}`)
    onProgress(batch.next_start, batch.page_count)
    if (batch.done) return
    next = batch.next_start
  }
}

const titleFromFilename = (name: string) =>
  name
    .replace(/\.pdf$/i, '')
    .replace(/[_-]+/g, ' ')
    .trim()

export function Documents() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [uploadLabels, setUploadLabels] = useState<string[]>([])
  const [jobs, setJobs] = useState<UploadJob[]>([])
  const [busyDoc, setBusyDoc] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)

  const labels = useQuery({ queryKey: ['admin', 'labels'], queryFn: () => get<Label[]>('/admin/labels') })
  const docs = useQuery({
    queryKey: ['admin', 'documents'],
    queryFn: () => get<AdminDocument[]>('/admin/documents'),
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'processing') ? 5000 : false),
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin', 'documents'] })

  const updateJob = (key: string, patch: Partial<UploadJob>) =>
    setJobs((prev) => prev.map((j) => (j.key === key ? { ...j, ...patch } : j)))

  const uploadFile = async (file: File) => {
    const key = `${file.name}-${crypto.randomUUID()}`
    setJobs((prev) => [{ key, name: file.name, phase: 'registering', pagesDone: 0, pageCount: null }, ...prev])
    try {
      const { document, upload } = await post<{
        document: DocumentRow
        upload: { path: string; token: string }
      }>('/admin/documents', { title: titleFromFilename(file.name), filename: file.name, label_ids: uploadLabels })

      updateJob(key, { phase: 'uploading' })
      const { error: uploadError } = await supabase.storage
        .from(STORAGE_BUCKET)
        .uploadToSignedUrl(upload.path, upload.token, file, { contentType: 'application/pdf' })
      if (uploadError) throw uploadError

      updateJob(key, { phase: 'ingesting' })
      refresh()
      await runIngestion(document.id, 0, (done, total) => updateJob(key, { pagesDone: done, pageCount: total }))
      updateJob(key, { phase: 'done' })
    } catch (e) {
      updateJob(key, { phase: 'error', error: (e as Error).message })
    } finally {
      refresh()
    }
  }

  const onFiles = async (files: FileList | null) => {
    if (!files) return
    const pdfs = Array.from(files).filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    for (const file of pdfs) await uploadFile(file) // sequential: keeps ingestion load predictable
    if (fileInput.current) fileInput.current.value = ''
  }

  const withBusy = async (id: string, label: string, fn: () => Promise<void>) => {
    setBusyDoc((b) => ({ ...b, [id]: label }))
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e)
    } finally {
      setBusyDoc((b) => {
        const next = { ...b }
        delete next[id]
        return next
      })
      refresh()
    }
  }

  const reingest = (d: AdminDocument, fromStart: boolean) =>
    withBusy(d.id, 'Ingesting…', () =>
      runIngestion(d.id, fromStart ? 0 : d.pages_processed, (done, total) =>
        setBusyDoc((b) => ({ ...b, [d.id]: `Ingesting ${done}/${total}…` })),
      ),
    )

  const remove = (d: AdminDocument) => {
    if (!confirm(`Delete “${d.title}”? This removes the PDF and its index.`)) return
    withBusy(d.id, 'Deleting…', () => del(`/admin/documents/${d.id}`))
  }

  const setDocLabels = (d: AdminDocument, ids: string[]) => {
    queryClient.setQueryData<AdminDocument[]>(['admin', 'documents'], (prev) =>
      prev?.map((x) => (x.id === d.id ? { ...x, label_ids: ids } : x)),
    )
    put(`/admin/documents/${d.id}/labels`, { label_ids: ids }).catch(setError)
  }

  const labelList = labels.data ?? []

  return (
    <div className="space-y-5">
      <Card className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-medium">Upload reports</h2>
            <p className="text-sm text-slate-500">PDFs are split into pages, indexed and tagged with the libraries you choose.</p>
          </div>
          <Button onClick={() => fileInput.current?.click()}>
            <Upload className="size-4" /> Choose PDFs
          </Button>
          <input ref={fileInput} type="file" accept="application/pdf" multiple hidden onChange={(e) => onFiles(e.target.files)} />
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">Add to libraries:</span>
          <LabelToggles labels={labelList} status={labels.status} selected={uploadLabels} onChange={setUploadLabels} />
        </div>
        {jobs.length > 0 && (
          <ul className="space-y-1.5">
            {jobs.map((j) => (
              <li key={j.key} className="flex items-center gap-3 text-sm">
                <span className="w-64 truncate">{j.name}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={j.phase === 'error' ? 'h-full bg-red-500' : 'h-full bg-indigo-500 transition-all'}
                    style={{
                      width:
                        j.phase === 'done' || j.phase === 'error'
                          ? '100%'
                          : j.pageCount
                            ? `${Math.max(5, (j.pagesDone / j.pageCount) * 100)}%`
                            : '5%',
                    }}
                  />
                </div>
                <span className="w-48 text-right text-xs text-slate-500">
                  {j.phase === 'error'
                    ? <span className="text-red-600">{j.error}</span>
                    : j.phase === 'ingesting' && j.pageCount
                      ? `Indexing page ${j.pagesDone} of ${j.pageCount}`
                      : j.phase}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <ErrorNote error={error ?? docs.error} />

      <Card>
        {docs.isLoading && <Spinner className="mx-auto my-8" />}
        {docs.data?.length === 0 && <EmptyState title="No documents yet">Upload a PDF to get started.</EmptyState>}
        {!!docs.data?.length && (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-4 py-2 font-medium">Libraries</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {docs.data.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="px-4 py-3">
                    <p className="font-medium">{d.title}</p>
                    <p className="text-xs text-slate-500">
                      {d.filename} · {d.page_count ?? '?'} pages
                    </p>
                    {d.empty_pages > 0 && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                        <AlertTriangle className="size-3.5" />
                        {d.empty_pages} page{d.empty_pages > 1 ? 's' : ''} with no extractable text (possibly scanned)
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <LabelToggles labels={labelList} status={labels.status} selected={d.label_ids} onChange={(ids) => setDocLabels(d, ids)} />
                    {d.label_ids.length === 0 && (
                      <p className="mt-1 text-xs text-amber-700">Not in any library: no user can search it.</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusCell doc={d} busy={busyDoc[d.id]} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      {(d.status === 'failed' || d.status === 'processing') && !busyDoc[d.id] && (
                        <Button variant="secondary" onClick={() => reingest(d, false)}>
                          Resume
                        </Button>
                      )}
                      <Button variant="ghost" title="Re-index from scratch" disabled={!!busyDoc[d.id]} onClick={() => reingest(d, true)}>
                        <RefreshCw className="size-4" />
                      </Button>
                      <Button variant="ghost" title="Delete" disabled={!!busyDoc[d.id]} onClick={() => remove(d)}>
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

function StatusCell({ doc, busy }: { doc: AdminDocument; busy?: string }) {
  if (busy) return <span className="text-xs text-indigo-600">{busy}</span>
  const styles: Record<string, string> = {
    ready: 'bg-green-50 text-green-700',
    processing: 'bg-indigo-50 text-indigo-700',
    uploaded: 'bg-slate-100 text-slate-600',
    failed: 'bg-red-50 text-red-700',
  }
  return (
    <div className="space-y-1">
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[doc.status]}`}>
        {doc.status}
        {doc.status === 'processing' && doc.page_count ? ` ${doc.pages_processed}/${doc.page_count}` : ''}
      </span>
      {doc.error && <p className="max-w-56 text-xs text-red-600">{doc.error}</p>}
    </div>
  )
}
