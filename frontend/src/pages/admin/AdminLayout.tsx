import clsx from 'clsx'
import { NavLink, Outlet } from 'react-router-dom'

const tabs = [
  { to: '/admin', label: 'Insights', end: true },
  { to: '/admin/documents', label: 'Documents' },
  { to: '/admin/labels', label: 'Libraries' },
  { to: '/admin/users', label: 'Users' },
]

export function AdminLayout() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Administration</h1>
          <nav className="flex gap-1 rounded-lg bg-slate-100 p-1">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  clsx(
                    'rounded-md px-3 py-1 text-sm font-medium',
                    isActive ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900',
                  )
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <Outlet />
      </div>
    </div>
  )
}
