import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Card, EmptyState, ErrorNote, Spinner } from '../../components/ui'
import { get } from '../../lib/api'
import type { AdminStats, QueryLog, Verdict } from '../../lib/types'
import { QueryTrace } from './QueryTrace'

const VERDICT_STYLE: Record<string, string> = {
  grounded: 'bg-green-50 text-green-700',
  partial: 'bg-amber-50 text-amber-700',
  low_confidence: 'bg-red-50 text-red-700',
  no_sources: 'bg-slate-100 text-slate-600',
  not_applicable: 'bg-slate-100 text-slate-500',
  unchecked: 'bg-slate-100 text-slate-500',
}

const FILTERS: { value: Verdict | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'low_confidence', label: 'Low confidence' },
  { value: 'partial', label: 'Partial' },
  { value: 'no_sources', label: 'Knowledge gaps' },
  { value: 'grounded', label: 'Grounded' },
]

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </Card>
  )
}

export function Insights() {
  const [verdict, setVerdict] = useState<Verdict | ''>('')
  const [open, setOpen] = useState<string | null>(null)
  const stats = useQuery({ queryKey: ['admin', 'stats'], queryFn: () => get<AdminStats>('/admin/stats') })
  const logs = useQuery({
    queryKey: ['admin', 'logs', verdict],
    queryFn: () => get<QueryLog[]>(`/admin/query-logs?limit=200${verdict ? `&verdict=${verdict}` : ''}`),
  })

  const s = stats.data
  const feedbackTotal = s ? s.thumbs_up + s.thumbs_down : 0

  return (
    <div className="space-y-5">
      <ErrorNote error={stats.error ?? logs.error} />
      {s && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Documents" value={`${s.documents_ready}/${s.documents}`} hint={`${s.pages} pages indexed`} />
          <Stat label="Questions asked" value={s.queries} hint={`${s.users} users`} />
          <Stat
            label="Avg. groundedness"
            value={s.avg_grounded === null ? '–' : `${Math.round(s.avg_grounded * 100)}%`}
            hint={`${s.regenerated} answers revised by the evaluator`}
          />
          <Stat
            label="Knowledge gaps"
            value={s.unanswered ?? 0}
            hint="questions no document could answer"
          />
          <Stat
            label="Helpful"
            value={feedbackTotal ? `${Math.round((s.thumbs_up / feedbackTotal) * 100)}%` : '–'}
            hint={`${s.thumbs_up} up · ${s.thumbs_down} down`}
          />
        </div>
      )}

      <Card>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
          <h2 className="font-medium">Recent questions</h2>
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setVerdict(f.value)}
                className={clsx(
                  'rounded-full px-2.5 py-0.5 text-xs font-medium',
                  verdict === f.value ? 'bg-slate-800 text-white dark:bg-indigo-600' : 'bg-slate-100 text-slate-600',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        {logs.isLoading && <Spinner className="mx-auto my-8" />}
        {logs.data?.length === 0 && <EmptyState title="No questions yet" />}
        {!!logs.data?.length && (
          <table className="w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {logs.data.map((log) => (
                <Fragment key={log.id}>
                  <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === log.id ? null : log.id)}>
                    <td className="px-4 py-2.5">
                      <p className="line-clamp-1">{log.question}</p>
                      <p className="text-xs text-slate-400">
                        {log.profiles?.email} · {new Date(log.created_at).toLocaleString()}
                      </p>
                    </td>
                    <td className="px-2 py-2.5">
                      {log.verdict && (
                        <span className={clsx('whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium', VERDICT_STYLE[log.verdict])}>
                          {log.verdict.replace('_', ' ')}
                          {log.grounded_score !== null && ` ${Math.round(log.grounded_score * 100)}%`}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2.5 text-xs text-slate-500">{log.regenerated && 'revised'}</td>
                    <td className="px-2 py-2.5">
                      {log.messages?.feedback === 1 && <ThumbsUp className="size-4 text-green-600" />}
                      {log.messages?.feedback === -1 && <ThumbsDown className="size-4 text-red-600" />}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right text-xs tabular-nums text-slate-500">
                      {log.latency_ms !== null && `${(log.latency_ms / 1000).toFixed(1)}s`}
                    </td>
                  </tr>
                  {open === log.id && (
                    <tr>
                      <td colSpan={5} className="bg-slate-50 px-4 py-3 text-sm text-slate-700">
                        <QueryTrace log={log} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
