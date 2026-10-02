import clsx from 'clsx'
import { BookOpen, LogOut, MessagesSquare, Settings } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  clsx(
    'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium',
    isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100',
  )

export function Layout() {
  const { me, signOut } = useAuth()
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-slate-200 bg-white px-4">
        <span className="font-semibold text-slate-900">Research Assistant</span>
        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={linkClass}>
            <MessagesSquare className="size-4" /> Ask
          </NavLink>
          <NavLink to="/library" className={linkClass}>
            <BookOpen className="size-4" /> Library
          </NavLink>
          {me?.role === 'admin' && (
            <NavLink to="/admin" className={linkClass}>
              <Settings className="size-4" /> Admin
            </NavLink>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
          <span className="hidden sm:inline">{me?.email}</span>
          <button onClick={signOut} className="flex items-center gap-1 hover:text-slate-800" title="Sign out">
            <LogOut className="size-4" />
          </button>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
