import { lazy, Suspense } from 'react'
import type { ViewerTarget } from './PdfViewer'
import { Spinner } from './ui'

// pdf.js is large; load it only when a document is opened.
const PdfViewer = lazy(() => import('./PdfViewer'))

export type { ViewerTarget }

export function LazyPdfViewer(props: { target: ViewerTarget; onClose: () => void }) {
  return (
    <Suspense fallback={<Spinner className="mx-auto mt-10" />}>
      <PdfViewer {...props} />
    </Suspense>
  )
}
