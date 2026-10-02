import clsx from 'clsx'
import type { Label } from '../../lib/types'

/** Row of clickable library pills; selected ones are filled. */
export function LabelToggles({
  labels,
  selected,
  onChange,
  disabled,
}: {
  labels: Label[]
  selected: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}) {
  if (!labels.length) return <span className="text-xs text-slate-400">No libraries yet</span>
  return (
    <div className="flex flex-wrap gap-1">
      {labels.map((l) => {
        const on = selected.includes(l.id)
        return (
          <button
            key={l.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(on ? selected.filter((s) => s !== l.id) : [...selected, l.id])}
            className={clsx(
              'rounded-full border px-2 py-0.5 text-xs font-medium transition-colors disabled:opacity-50',
              on ? 'border-transparent text-white' : 'border-slate-300 text-slate-500 hover:border-slate-400',
            )}
            style={on ? { backgroundColor: l.color } : undefined}
          >
            {l.name}
          </button>
        )
      })}
    </div>
  )
}
