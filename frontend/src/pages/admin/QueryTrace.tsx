import clsx from 'clsx'
import { useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import type { ClaimCheck, EvalResult, QueryLog } from '../../lib/types'

type Tab = 'answer' | 'query' | 'retrieval' | 'evaluator'

const TABS: { id: Tab; label: string }[] = [
  { id: 'answer', label: 'Answer' },
  { id: 'query', label: 'Query Agent' },
  { id: 'retrieval', label: 'Retrieval (RAG)' },
  { id: 'evaluator', label: 'Evaluator Agent' },
]

const CLAIM_STYLE: Record<ClaimCheck['verdict'], string> = {
  supported: 'bg-green-50 text-green-700',
  partial: 'bg-amber-50 text-amber-700',
  unsupported: 'bg-red-50 text-red-700',
}

// Tailwind's reset strips list and paragraph styling, so restore it for answers.
const MD: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-0.5 pl-5">{children}</ol>,
  strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
}

function Label({ children }: { children: React.ReactNode }) {
  return <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">{children}</p>
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-slate-400">{children}</p>
}

/** Expanded view of one logged question: what each stage of the pipeline produced. */
export function QueryTrace({ log }: { log: QueryLog }) {
  const [tab, setTab] = useState<Tab>('answer')
  const m = log.messages

  return (
    <div className="space-y-3">
      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              '-mb-px border-b-2 px-3 py-1.5 text-xs font-medium',
              tab === t.id ? 'border-indigo-600 text-indigo-700' : 'border-transparent text-slate-500 hover:text-slate-700',
            )}
          >
            {t.label}
            {t.id === 'retrieval' && log.retrieved?.length ? ` · ${log.retrieved.length}` : ''}
          </button>
        ))}
      </div>

      {tab === 'answer' && (
        <div className="space-y-2">
          {m ? (
            <>
              <div className="text-sm text-slate-700">
                <ReactMarkdown components={MD}>{m.content}</ReactMarkdown>
              </div>
              {m.feedback_note && <p className="text-xs italic">“{m.feedback_note}”</p>}
            </>
          ) : (
            <Empty>The answer wasn't saved.</Empty>
          )}
          <p className="text-xs text-slate-400">
            {log.input_tokens} input / {log.output_tokens} output tokens across all agents
            {log.latency_ms !== null && ` · ${(log.latency_ms / 1000).toFixed(1)}s end to end`}
          </p>
        </div>
      )}

      {tab === 'query' && <QueryAgentOutput log={log} />}
      {tab === 'retrieval' && <RetrievalOutput log={log} />}
      {tab === 'evaluator' && <EvaluatorOutput log={log} />}
    </div>
  )
}

function QueryAgentOutput({ log }: { log: QueryLog }) {
  const p = log.plan
  if (!p) return <Empty>No plan recorded for this question.</Empty>
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <Label>Original question</Label>
        <p>{log.question}</p>
      </div>
      <div>
        <Label>Standalone question</Label>
        <p>{p.standalone_question || '–'}</p>
      </div>
      <div>
        <Label>Sub-queries sent to search</Label>
        {p.sub_queries.length ? (
          <ol className="list-decimal space-y-0.5 pl-5">
            {p.sub_queries.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        ) : (
          <Empty>None</Empty>
        )}
      </div>
      <div>
        <Label>Keywords for keyword search</Label>
        {p.keywords.length ? (
          <div className="flex flex-wrap gap-1">
            {p.keywords.map((k) => (
              <span key={k} className="rounded bg-white px-1.5 py-0.5 font-mono text-xs ring-1 ring-slate-200">
                {k}
              </span>
            ))}
          </div>
        ) : (
          <Empty>None (the sub-queries were used instead)</Empty>
        )}
      </div>
      <div className="md:col-span-2">
        <Label>Needs retrieval</Label>
        <p>{p.needs_retrieval ? 'Yes' : `No, replied directly: “${p.direct_reply}”`}</p>
      </div>
    </div>
  )
}

function RetrievalOutput({ log }: { log: QueryLog }) {
  const rows = log.retrieved ?? []
  if (!rows.length) {
    return <Empty>{log.plan?.needs_retrieval === false ? 'Search was skipped for this question.' : 'Search returned no pages.'}</Empty>
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500">
        Pages passed to the Answer Agent, best first. The text shown is the chunk that matched; the agent received the whole page.
      </p>
      <ol className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="rounded-md bg-white p-3 ring-1 ring-slate-200">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded bg-indigo-50 px-1.5 py-0.5 font-semibold text-indigo-700">{r.id}</span>
              <span className="font-medium text-slate-700">{r.document_title}</span>
              <span className="text-slate-500">
                page {r.page_index}
                {r.printed_label && r.printed_label !== String(r.page_index) && ` (printed ${r.printed_label})`}
              </span>
              {r.score !== null && <span className="tabular-nums text-slate-400">score {r.score.toFixed(4)}</span>}
              <span
                className={clsx(
                  'ml-auto rounded-full px-2 py-0.5 font-medium',
                  r.cited ? 'bg-green-50 text-green-700' : 'bg-slate-100 text-slate-500',
                )}
              >
                {r.cited ? 'Cited' : 'Not cited'}
              </span>
            </div>
            <p className="mt-1.5 line-clamp-4 whitespace-pre-wrap text-xs leading-relaxed text-slate-600">{r.matched}</p>
          </li>
        ))}
      </ol>
      {rows.some((r) => r.score === null) && (
        <p className="text-xs text-slate-400">Scores weren't recorded for questions asked before this view was added.</p>
      )}
    </div>
  )
}

function EvaluatorOutput({ log }: { log: QueryLog }) {
  const final = log.messages?.eval ?? null
  return (
    <div className="space-y-4">
      {log.first_draft && (
        <div className="rounded-md border border-amber-200 bg-amber-50/50 p-3">
          <Label>First draft, rejected by the evaluator</Label>
          <div className="text-sm text-slate-600">
            <ReactMarkdown components={MD}>{log.first_draft.answer}</ReactMarkdown>
          </div>
          <div className="mt-2">
            <EvalDetails ev={log.first_draft.eval} />
          </div>
        </div>
      )}
      <div>
        {log.first_draft && <Label>Final answer</Label>}
        {final ? <EvalDetails ev={final} /> : <Empty>No evaluation was saved for this answer.</Empty>}
      </div>
    </div>
  )
}

function EvalDetails({ ev }: { ev: EvalResult }) {
  return (
    <div className="space-y-2">
      <p className="text-sm">
        <span className="font-medium">{ev.verdict.replace('_', ' ')}</span>
        {ev.grounded_score !== null && ` · grounded score ${Math.round(ev.grounded_score * 100)}%`}
        {ev.summary && <span className="text-slate-600"> · {ev.summary}</span>}
      </p>
      {ev.claims.length ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-400">
              <th className="py-1 pr-2 font-medium">Claim</th>
              <th className="px-2 py-1 font-medium">Cited</th>
              <th className="px-2 py-1 font-medium">Verdict</th>
              <th className="px-2 py-1 font-medium">Citation</th>
              <th className="py-1 pl-2 font-medium">Evidence / note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 align-top">
            {ev.claims.map((c, i) => (
              <tr key={i}>
                <td className="py-1.5 pr-2 text-slate-700">{c.claim}</td>
                <td className="whitespace-nowrap px-2 py-1.5 text-slate-500">{c.source_ids.join(', ') || '–'}</td>
                <td className="px-2 py-1.5">
                  <span className={clsx('whitespace-nowrap rounded-full px-2 py-0.5 font-medium', CLAIM_STYLE[c.verdict])}>
                    {c.verdict}
                  </span>
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 text-slate-600">{c.citation_correct ? 'correct' : 'wrong'}</td>
                <td className="py-1.5 pl-2 text-slate-600">
                  {c.evidence_quote && <span className="italic">“{c.evidence_quote}”</span>}
                  {c.note && <span className="block text-slate-500">{c.note}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>No factual claims to check.</Empty>
      )}
    </div>
  )
}
