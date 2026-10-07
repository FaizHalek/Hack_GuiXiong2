import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Pencil, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Button, Card, DocTypePill, EmptyState, ErrorNote, Input, Spinner } from '../../components/ui'
import { del, get, patch, post, postForm, put } from '../../lib/api'
import { DOC_TYPES, formatIssued } from '../../lib/docTypes'
import type { DocType, DocumentRow, Label } from '../../lib/types'
import { LabelToggles } from './LabelToggles'

type AdminDocument = DocumentRow & { empty_pages: number }

interface UploadJob {
  key: string
  name: string
  phase: 'uploading' | 'ingesting' | 'done' | 'error'
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

/** Guess the document type from words in the file name; the admin can correct it afterwards. */
function guessType(name: string): DocType {
  const n = name.toLowerCase()
  if (/\bsop\b|standard.operating|procedure/.test(n)) return 'sop'
  if (/circular|pekeliling/.test(n)) return 'circular'
  if (/minute|minit|meeting|mesyuarat/.test(n)) return 'minutes'
  if (/guideline|garis.panduan/.test(n)) return 'guideline'
  if (/policy|dasar/.test(n)) return 'policy'
  if (/report|laporan/.test(n)) return 'report'
  return 'other'
}

const selectClass = 'rounded-md border border-slate-300 bg-surface px-2 py-1.5 text-sm'

export function Documents() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [uploadLabels, setUploadLabels] = useState<string[]>([])
  const [uploadType, setUploadType] = useState<DocType | 'auto'>('auto')
  const [uploadIssued, setUploadIssued] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
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
    setJobs((prev) => [{ key, name: file.name, phase: 'uploading', pagesDone: 0, pageCount: null }, ...prev])
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('title', titleFromFilename(file.name))
      form.append('doc_type', uploadType === 'auto' ? guessType(file.name) : uploadType)
      if (uploadIssued) form.append('issued_on', uploadIssued)
      uploadLabels.forEach((id) => form.append('label_ids', id))
      const document = await postForm<DocumentRow>('/admin/documents', form)

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
    if (!confirm(`Delete “${d.title}”? This removes the PDF from local storage and from the search index.`)) return
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
            <h2 className="font-medium">Upload documents</h2>
            <p className="text-sm text-slate-500">
              PDFs are saved to local storage, split into pages and indexed for search in the collections you choose.
            </p>
          </div>
          <Button onClick={() => fileInput.current?.click()}>
            <Upload className="size-4" /> Choose PDFs
          </Button>
          <input ref={fileInput} type="file" accept="application/pdf" multiple hidden onChange={(e) => onFiles(e.target.files)} />
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-slate-500">Type:</span>
            <select value={uploadType} onChange={(e) => setUploadType(e.target.value as DocType | 'auto')} className={selectClass}>
              <option value="auto">Detect from file name</option>
              {DOC_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="whitespace-nowrap text-slate-500">Issued on:</span>
            <div className="w-40">
              <Input type="date" value={uploadIssued} onChange={(e) => setUploadIssued(e.target.value)} />
            </div>
          </label>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="whitespace-nowrap text-slate-500">Add to collections:</span>
          <LabelToggles labels={labelList} status={labels.status} selected={uploadLabels} onChange={setUploadLabels} />
        </div>
        {uploadLabels.length === 0 && labelList.length > 0 && (
          <p className="text-xs text-amber-700">Choose at least one collection, or no user will be able to search the uploads.</p>
        )}
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
                <th className="px-4 py-2 font-medium">Collections</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {docs.data.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="px-4 py-3">
                    {editing === d.id ? (
                      <MetadataForm doc={d} onDone={() => setEditing(null)} onSaved={refresh} />
                    ) : (
                      <>
                        <div className="flex items-center gap-2">
                          <DocTypePill type={d.doc_type} />
                          <p className="font-medium">{d.title}</p>
                        </div>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {[d.reference_no, d.issued_on && `issued ${formatIssued(d.issued_on)}`, d.filename, `${d.page_count ?? '?'} pages`]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                      </>
                    )}
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
                      <p className="mt-1 text-xs text-amber-700">Not in any collection: no user can search it.</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusCell doc={d} busy={busyDoc[d.id]} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" title="Edit details" disabled={editing === d.id} onClick={() => setEditing(d.id)}>
                        <Pencil className="size-4" />
                      </Button>
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

function MetadataForm({ doc, onDone, onSaved }: { doc: AdminDocument; onDone: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(doc.title)
  const [docType, setDocType] = useState<DocType>(doc.doc_type)
  const [reference, setReference] = useState(doc.reference_no ?? '')
  const [issued, setIssued] = useState(doc.issued_on ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await patch(`/admin/documents/${doc.id}`, {
        title,
        doc_type: docType,
        reference_no: reference || null,
        issued_on: issued || null,
      })
      onSaved()
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={save} className="space-y-2">
      <Input required value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
      <div className="flex flex-wrap gap-2">
        <select value={docType} onChange={(e) => setDocType(e.target.value as DocType)} className={selectClass} aria-label="Type">
          {DOC_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <div className="w-40">
          <Input placeholder="Reference no." value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
        <div className="w-40">
          <Input type="date" value={issued} onChange={(e) => setIssued(e.target.value)} aria-label="Issued on" />
        </div>
      </div>
      <ErrorNote error={error} />
      <div className="flex gap-2">
        <Button type="submit" loading={saving}>
          Save
        </Button>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
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
