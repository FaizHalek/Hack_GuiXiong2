import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../../auth/AuthProvider'
import { Button, Card, ErrorNote, Input, Spinner } from '../../components/ui'
import { get, patch, post, put } from '../../lib/api'
import type { AdminUser, Label, Role } from '../../lib/types'
import { LabelToggles } from './LabelToggles'

export function Users() {
  const { me } = useAuth()
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: () => get<AdminUser[]>('/admin/users') })
  const labels = useQuery({ queryKey: ['admin', 'labels'], queryFn: () => get<Label[]>('/admin/labels') })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('user')
  const [inviteLabels, setInviteLabels] = useState<string[]>([])
  const [inviting, setInviting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const setUsers = (fn: (u: AdminUser[]) => AdminUser[]) =>
    queryClient.setQueryData<AdminUser[]>(['admin', 'users'], (prev) => (prev ? fn(prev) : prev))

  const invite = async (e: FormEvent) => {
    e.preventDefault()
    setInviting(true)
    setError(null)
    setNotice(null)
    try {
      await post('/admin/users/invite', { email, role, label_ids: inviteLabels })
      setNotice(`Invitation sent to ${email}.`)
      setEmail('')
      setInviteLabels([])
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    } catch (err) {
      setError(err)
    } finally {
      setInviting(false)
    }
  }

  const changeRole = (u: AdminUser, next: Role) => {
    setUsers((list) => list.map((x) => (x.id === u.id ? { ...x, role: next } : x)))
    patch(`/admin/users/${u.id}`, { role: next }).catch((err) => {
      setError(err)
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    })
  }

  const changeLabels = (u: AdminUser, ids: string[]) => {
    setUsers((list) => list.map((x) => (x.id === u.id ? { ...x, label_ids: ids } : x)))
    put(`/admin/users/${u.id}/labels`, { label_ids: ids }).catch((err) => {
      setError(err)
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    })
  }

  const labelList = labels.data ?? []

  return (
    <div className="space-y-5">
      <Card className="p-4">
        <form onSubmit={invite} className="space-y-3">
          <h2 className="font-medium">Invite a user</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="email"
              required
              placeholder="name@customer.com"
              className="w-72"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <Button type="submit" loading={inviting}>
              Send invite
            </Button>
          </div>
          {role === 'user' && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-500">Can search:</span>
              <LabelToggles labels={labelList} selected={inviteLabels} onChange={setInviteLabels} />
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
                <th className="px-4 py-2 font-medium">Library access</th>
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
                      className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm disabled:opacity-60"
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    {u.role === 'admin' ? (
                      <span className="text-xs text-slate-500">All libraries</span>
                    ) : (
                      <LabelToggles labels={labelList} selected={u.label_ids} onChange={(ids) => changeLabels(u, ids)} />
                    )}
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
