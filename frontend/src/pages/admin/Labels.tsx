import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Button, Card, EmptyState, ErrorNote, Input, LabelPill, Spinner } from '../../components/ui'
import { del, get, patch, post } from '../../lib/api'
import type { Label } from '../../lib/types'

const COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#475569']

interface Draft {
  name: string
  description: string
  color: string
}

const empty: Draft = { name: '', description: '', color: COLORS[0] }

export function Labels() {
  const queryClient = useQueryClient()
  const labels = useQuery({ queryKey: ['admin', 'labels'], queryFn: () => get<Label[]>('/admin/labels') })
  const [draft, setDraft] = useState<Draft>(empty)
  const [editing, setEditing] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['admin', 'labels'] })
    queryClient.invalidateQueries({ queryKey: ['me'] })
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (editing) await patch(`/admin/labels/${editing}`, draft)
      else await post('/admin/labels', draft)
      setDraft(empty)
      setEditing(null)
      refresh()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (l: Label) => {
    if (!confirm(`Delete the “${l.name}” library? Documents stay, but lose this label and users lose access through it.`)) return
    try {
      await del(`/admin/labels/${l.id}`)
      refresh()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="grid gap-5 md:grid-cols-[1fr_320px]">
      <Card>
        {labels.isLoading && <Spinner className="mx-auto my-8" />}
        {labels.data?.length === 0 && (
          <EmptyState title="No libraries yet">Create one per company or research collection, then tag documents with it.</EmptyState>
        )}
        <ul className="divide-y divide-slate-100">
          {labels.data?.map((l) => (
            <li key={l.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <LabelPill name={l.name} color={l.color} />
                {l.description && <p className="mt-1 text-sm text-slate-500">{l.description}</p>}
              </div>
              <span className="text-xs text-slate-500">
                {l.document_count} docs · {l.user_count} users
              </span>
              <Button
                variant="ghost"
                title="Edit"
                onClick={() => {
                  setEditing(l.id)
                  setDraft({ name: l.name, description: l.description, color: l.color })
                }}
              >
                <Pencil className="size-4" />
              </Button>
              <Button variant="ghost" title="Delete" onClick={() => remove(l)}>
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="h-fit p-4">
        <form onSubmit={submit} className="space-y-3">
          <h2 className="font-medium">{editing ? 'Edit library' : 'New library'}</h2>
          <Input required placeholder="Name, e.g. Acme Corp" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <Input
            placeholder="Description (optional)"
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
          <div className="flex gap-1.5">
            {COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setDraft({ ...draft, color: c })}
                className="size-6 rounded-full ring-offset-2"
                style={{ backgroundColor: c, boxShadow: draft.color === c ? `0 0 0 2px white, 0 0 0 4px ${c}` : undefined }}
                title={c}
              />
            ))}
          </div>
          <ErrorNote error={error} />
          <div className="flex gap-2">
            <Button type="submit" loading={saving}>
              {editing ? 'Save' : 'Create'}
            </Button>
            {editing && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditing(null)
                  setDraft(empty)
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </Card>
    </div>
  )
}
