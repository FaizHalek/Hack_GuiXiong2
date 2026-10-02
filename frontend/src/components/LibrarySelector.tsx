import clsx from 'clsx'
import { Check } from 'lucide-react'
import type { Label } from '../lib/types'

export function LibrarySelector({
  labels,
  selected,
  onChange,
}: {
  labels: Label[]
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  if (labels.length === 0) {
    return <p className="px-1 text-sm text-slate-500">You haven't been given access to any research libraries yet.</p>
  }
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id])
  const allSelected = selected.length === labels.length

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between px-1">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Libraries</p>
        <button
          className="text-xs text-indigo-600 hover:underline"
          onClick={() => onChange(allSelected ? [] : labels.map((l) => l.id))}
        >
          {allSelected ? 'Clear' : 'All'}
        </button>
      </div>
      {labels.map((label) => {
        const on = selected.includes(label.id)
        return (
          <button
            key={label.id}
            onClick={() => toggle(label.id)}
            className={clsx(
              'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm',
              on ? 'bg-white shadow-xs ring-1 ring-slate-200' : 'text-slate-600 hover:bg-slate-100',
            )}
          >
            <span
              className={clsx(
                'flex size-4 items-center justify-center rounded border',
                on ? 'border-transparent text-white' : 'border-slate-300',
              )}
              style={on ? { backgroundColor: label.color } : undefined}
            >
              {on && <Check className="size-3" />}
            </span>
            <span className="truncate">{label.name}</span>
          </button>
        )
      })}
    </div>
  )
}
