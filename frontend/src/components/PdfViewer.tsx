import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, ExternalLink, Minus, Plus, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import { get } from '../lib/api'
import { escapeHtml, normaliseForMatch, runMatchesEvidence } from '../lib/citations'
import { Spinner } from './ui'

// Must be configured in the same module that renders <Document>/<Page>.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

export interface ViewerTarget {
  documentId: string
  page: number // 1-based physical page index
  title?: string
  printedLabel?: string | null
  snippet?: string
}

export default function PdfViewer({ target, onClose }: { target: ViewerTarget; onClose: () => void }) {
  // Manual paging is remembered per citation; clicking another citation jumps to its page.
  const targetKey = `${target.documentId}:${target.page}:${target.snippet ?? ''}`
  const [nav, setNav] = useState({ key: targetKey, page: target.page })
  const page = nav.key === targetKey ? nav.page : target.page
  const setPage = (update: number | ((p: number) => number)) =>
    setNav({ key: targetKey, page: typeof update === 'function' ? update(page) : update })
  const [numPages, setNumPages] = useState<number | null>(null)
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(600)
  const containerRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width - 32)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const { data, error, isLoading } = useQuery({
    queryKey: ['signed-url', target.documentId],
    queryFn: () => get<{ url: string; title: string; page_count: number }>(`/documents/${target.documentId}/signed-url`),
    staleTime: 50 * 60_000,
  })

  const evidence = useMemo(() => normaliseForMatch(target.snippet ?? ''), [target.snippet])
  const highlightThisPage = page === target.page && evidence.length > 0

  const renderText = useCallback(
    ({ str }: { str: string }) =>
      highlightThisPage && runMatchesEvidence(str, evidence) ? `<mark>${escapeHtml(str)}</mark>` : escapeHtml(str),
    [highlightThisPage, evidence],
  )

  const scrollToHighlight = () => {
    const mark = scrollRef.current?.querySelector('.react-pdf__Page__textContent mark')
    mark?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  const total = numPages ?? data?.page_count ?? null
  const title = target.title ?? data?.title ?? 'Document'

  return (
    <div ref={containerRef} className="flex h-full flex-col border-l border-slate-200 bg-slate-100">
      <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={title}>
            {title}
          </p>
          <p className="text-xs text-slate-500">
            Page {page}
            {total ? ` of ${total}` : ''}
            {page === target.page && target.printedLabel ? ` · printed as “${target.printedLabel}”` : ''}
          </p>
        </div>
        <button className="rounded p-1 hover:bg-slate-100" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} title="Zoom out">
          <Minus className="size-4" />
        </button>
        <span className="w-10 text-center text-xs text-slate-500">{Math.round(zoom * 100)}%</span>
        <button className="rounded p-1 hover:bg-slate-100" onClick={() => setZoom((z) => Math.min(3, z + 0.25))} title="Zoom in">
          <Plus className="size-4" />
        </button>
        {data?.url && (
          <a className="rounded p-1 hover:bg-slate-100" href={data.url} target="_blank" rel="noreferrer" title="Open PDF in a new tab">
            <ExternalLink className="size-4" />
          </a>
        )}
        <button className="rounded p-1 hover:bg-slate-100" onClick={onClose} title="Close viewer">
          <X className="size-4" />
        </button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto p-4">
        {isLoading && <Spinner className="mx-auto mt-10" />}
        {error && <p className="text-sm text-red-600">Couldn't load this document: {(error as Error).message}</p>}
        {data?.url && (
          <Document
            file={data.url}
            onLoadSuccess={(doc) => setNumPages(doc.numPages)}
            loading={<Spinner className="mx-auto mt-10" />}
            error={<p className="text-sm text-red-600">Couldn't render this PDF.</p>}
          >
            <Page
              key={`${page}-${highlightThisPage}`}
              pageNumber={page}
              width={width * zoom}
              className="mx-auto w-fit shadow-md"
              customTextRenderer={renderText}
              onRenderTextLayerSuccess={highlightThisPage ? scrollToHighlight : undefined}
            />
          </Document>
        )}
      </div>

      <div className="flex items-center justify-center gap-3 border-t border-slate-200 bg-white py-2">
        <button
          className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
          title="Previous page"
        >
          <ChevronLeft className="size-5" />
        </button>
        {page !== target.page && (
          <button className="text-xs text-indigo-600 hover:underline" onClick={() => setPage(target.page)}>
            Back to cited page {target.page}
          </button>
        )}
        <button
          className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"
          disabled={total !== null && page >= total}
          onClick={() => setPage((p) => p + 1)}
          title="Next page"
        >
          <ChevronRight className="size-5" />
        </button>
      </div>
    </div>
  )
}
