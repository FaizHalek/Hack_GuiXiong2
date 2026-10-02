import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, ChevronDown, CircleDashed, FileText, Loader2, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { post } from '../lib/api'
import { citationIdFromHref, linkCitations } from '../lib/citations'
import type { ChatMessage, Citation, EvalResult } from '../lib/types'

const STATUS_TEXT: Record<string, string> = {
  planning: 'Understanding the question…',
  retrieving: 'Searching the research libraries…',
  answering: 'Writing the answer…',
  evaluating: 'Checking the answer against its sources…',
  regenerating: 'Revising the answer to fix unsupported claims…',
}

export function AnswerMessage({
  message,
  onOpenCitation,
}: {
  message: ChatMessage
  onOpenCitation: (citation: Citation) => void
}) {
  // While streaming, citations come from the retrieved sources; once final, from the cited set.
  const pool = message.citations.length ? message.citations : (message.sources ?? [])
  const byId = new Map(pool.map((c) => [c.id, c]))
  const busy = message.status && message.status !== 'done' && message.status !== 'error'

  return (
    <div className="space-y-3">
      {busy && (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin" /> {STATUS_TEXT[message.status!]}
        </p>
      )}

      {message.content && (
        <div className="prose-answer text-[15px] leading-relaxed text-slate-800">
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                const id = citationIdFromHref(href)
                const citation = id ? byId.get(id) : undefined
                if (!id) return <a href={href}>{children}</a>
                return (
                  <button
                    type="button"
                    onClick={() => citation && onOpenCitation(citation)}
                    disabled={!citation}
                    title={citation ? `${citation.document_title}, page ${citation.page_index}` : 'Unknown source'}
                    className={clsx(
                      'mx-0.5 inline-flex items-center rounded px-1 align-baseline text-xs font-semibold',
                      citation ? 'bg-indigo-50 text-indigo-700 hover:bg-indigo-100' : 'bg-red-50 text-red-600',
                    )}
                  >
                    {id}
                  </button>
                )
              },
              p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
              ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5">{children}</ul>,
              ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5">{children}</ol>,
              strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
            }}
          >
            {linkCitations(message.content)}
          </ReactMarkdown>
        </div>
      )}

      {message.status === 'done' && message.citations.length > 0 && (
        <SourceList citations={message.citations} onOpen={onOpenCitation} />
      )}

      {message.status === 'done' && (
        <div className="flex flex-wrap items-center gap-3">
          {message.eval && <EvalBadge result={message.eval} />}
          {message.id && <FeedbackButtons messageId={message.id} initial={message.feedback ?? null} />}
        </div>
      )}
    </div>
  )
}

function SourceList({ citations, onOpen }: { citations: Citation[]; onOpen: (c: Citation) => void }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Sources</p>
      <ul className="space-y-1">
        {citations.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => onOpen(c)}
              className="flex w-full items-start gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-slate-100"
            >
              <span className="mt-0.5 rounded bg-indigo-50 px-1 text-xs font-semibold text-indigo-700">{c.id}</span>
              <FileText className="mt-0.5 size-4 shrink-0 text-slate-400" />
              <span className="min-w-0">
                <span className="font-medium text-slate-700">{c.document_title}</span>
                <span className="text-slate-500">
                  {' '}
                  · page {c.page_index}
                  {c.printed_label ? ` (printed ${c.printed_label})` : ''}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

const BADGES = {
  grounded: { text: 'Grounded in sources', className: 'bg-green-50 text-green-700', Icon: CheckCircle2 },
  partial: { text: 'Partially grounded', className: 'bg-amber-50 text-amber-700', Icon: AlertTriangle },
  low_confidence: { text: 'Low confidence: verify before use', className: 'bg-red-50 text-red-700', Icon: AlertTriangle },
  unchecked: { text: 'Not verified', className: 'bg-slate-100 text-slate-600', Icon: CircleDashed },
} as const

export function EvalBadge({ result }: { result: EvalResult }) {
  const [open, setOpen] = useState(false)
  if (!(result.verdict in BADGES)) return null
  const badge = BADGES[result.verdict as keyof typeof BADGES]
  const flagged = result.claims.filter((c) => c.verdict !== 'supported' || !c.citation_correct)

  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium', badge.className)}
      >
        <badge.Icon className="size-3.5" />
        {badge.text}
        {result.grounded_score !== null && ` · ${Math.round(result.grounded_score * 100)}%`}
        <ChevronDown className={clsx('size-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="mt-2 max-w-xl space-y-1.5 rounded-md border border-slate-200 bg-white p-3 text-slate-600">
          <p>{result.summary}</p>
          {flagged.length > 0 ? (
            <ul className="space-y-1">
              {flagged.map((c, i) => (
                <li key={i} className="border-l-2 border-amber-300 pl-2">
                  <span className="font-medium text-slate-700">“{c.claim}”</span>{' '}
                  <span className="text-slate-500">
                    {c.verdict}
                    {!c.citation_correct && ', citation mismatch'}
                    {c.note && `: ${c.note}`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-slate-500">Every claim was supported by the cited page.</p>
          )}
        </div>
      )}
    </div>
  )
}

function FeedbackButtons({ messageId, initial }: { messageId: string; initial: 1 | -1 | null }) {
  const [value, setValue] = useState<1 | -1 | null>(initial)
  const send = async (v: 1 | -1) => {
    setValue(v)
    try {
      await post(`/messages/${messageId}/feedback`, { value: v })
    } catch {
      setValue(initial)
    }
  }
  return (
    <div className="flex items-center gap-1 text-slate-400">
      <button
        type="button"
        onClick={() => send(1)}
        className={clsx('rounded p-1 hover:bg-slate-100', value === 1 && 'text-green-600')}
        title="Helpful"
      >
        <ThumbsUp className="size-3.5" />
      </button>
      <button
        type="button"
        onClick={() => send(-1)}
        className={clsx('rounded p-1 hover:bg-slate-100', value === -1 && 'text-red-600')}
        title="Not helpful"
      >
        <ThumbsDown className="size-3.5" />
      </button>
    </div>
  )
}
