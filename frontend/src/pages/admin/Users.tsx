import { useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../../auth/AuthProvider'
import { Button, Card, ErrorNote, Input, Spinner } from '../../components/ui'
import { del, get, patch, post, put } from '../../lib/api'
import type { AdminUser, Label, Role } from '../../lib/types'
import { LabelToggles } from './LabelToggles'

const MIN_PASSWORD = 8

export function Users() {
  const { me } = useAuth()
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: () => get<AdminUser[]>('/admin/users') })
  const labels = useQuery({ queryKey: ['admin', 'labels'], queryFn: () => get<Label[]>('/admin/labels') })
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('user')
  const [newLabels, setNewLabels] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
  const setUsers = (fn: (u: AdminUser[]) => AdminUser[]) =>
    queryClient.setQueryData<AdminUser[]>(['admin', 'users'], (prev) => (prev ? fn(prev) : prev))

  const create = async (e: FormEvent) => {
    e.preventDefault()
    setCreating(true)
    setError(null)
    setNotice(null)
    try {
      await post('/admin/users', { email, password, role, label_ids: role === 'user' ? newLabels : [] })
      setNotice(`Account created for ${email}. Share the password with them through a secure channel.`)
      setEmail('')
      setPassword('')
      setNewLabels([])
      refresh()
    } catch (err) {
      setError(err)
    } finally {
      setCreating(false)
    }
  }

  const changeRole = (u: AdminUser, next: Role) => {
    setUsers((list) => list.map((x) => (x.id === u.id ? { ...x, role: next } : x)))
    patch(`/admin/users/${u.id}`, { role: next }).catch((err) => {
      setError(err)
      refresh()
    })
  }

  const changeLabels = (u: AdminUser, ids: string[]) => {
    setUsers((list) => list.map((x) => (x.id === u.id ? { ...x, label_ids: ids } : x)))
    put(`/admin/users/${u.id}/labels`, { label_ids: ids }).catch((err) => {
      setError(err)
      refresh()
    })
  }

  const resetPassword = async (u: AdminUser) => {
    const next = prompt(`New password for ${u.email} (at least ${MIN_PASSWORD} characters):`)
    if (next === null) return
    setError(null)
    setNotice(null)
    try {
      await put(`/admin/users/${u.id}/password`, { password: next })
      setNotice(`Password updated for ${u.email}.`)
    } catch (err) {
      setError(err)
    }
  }

  const remove = async (u: AdminUser) => {
    if (!confirm(`Delete the account for ${u.email}? Their conversations are deleted too.`)) return
    setError(null)
    try {
      await del(`/admin/users/${u.id}`)
      refresh()
    } catch (err) {
      setError(err)
    }
  }

  const labelList = labels.data ?? []

  return (
    <div className="space-y-5">
      <Card className="p-4">
        <form onSubmit={create} className="space-y-3">
          <div>
            <h2 className="font-medium">Add a user</h2>
            <p className="text-sm text-slate-500">Accounts are stored locally. Users sign in with this email and password.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-64 max-w-full">
              <Input type="email" required placeholder="name@agency.gov" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="w-64 max-w-full">
              <Input
                type="password"
                required
                minLength={MIN_PASSWORD}
                autoComplete="new-password"
                placeholder={`Temporary password (${MIN_PASSWORD}+ characters)`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="rounded-md border border-slate-300 bg-surface px-2 py-1.5 text-sm"
            >
              <option value="user">Officer</option>
              <option value="admin">Admin</option>
            </select>
            <Button type="submit" loading={creating}>
              Add user
            </Button>
          </div>
          {role === 'user' && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-500">Can search:</span>
              <LabelToggles labels={labelList} status={labels.status} selected={newLabels} onChange={setNewLabels} />
            </div>
          )}
          {notice && <p className="text-sm text-green-700">{notice}</p>}
        </form>
      </Card>

      <ErrorNote error={error ?? users.error} />

      <Card>
        {users.isLoading && <Spinner className="mx-auto my-8" />}
        {users.data && (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-4 py-2 font-medium">User</th>
                <th className="px-4 py-2 font-medium">Role</th>
                <th className="px-4 py-2 font-medium">Collection access</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    {u.email}
                    {u.id === me?.id && <span className="ml-1 text-xs text-slate-400">(you)</span>}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role}
                      disabled={u.id === me?.id}
                      onChange={(e) => changeRole(u, e.target.value as Role)}
                      className="rounded-md border border-slate-300 bg-surface px-2 py-1 text-sm disabled:opacity-60"
                    >
                      <option value="user">Officer</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    {u.role === 'admin' ? (
                      <span className="text-xs text-slate-500">All collections</span>
                    ) : (
                      <LabelToggles labels={labelList} status={labels.status} selected={u.label_ids} onChange={(ids) => changeLabels(u, ids)} />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" title="Reset password" onClick={() => resetPassword(u)}>
                        <KeyRound className="size-4" />
                      </Button>
                      <Button variant="ghost" title="Delete user" disabled={u.id === me?.id} onClick={() => remove(u)}>
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
