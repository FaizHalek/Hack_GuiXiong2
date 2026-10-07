import clsx from 'clsx'
import { FolderOpen, Landmark, LogOut, MessagesSquare, Monitor, Moon, Settings, Sun } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { getTheme, setTheme, type Theme } from '../lib/theme'

const themeOrder: Theme[] = ['system', 'light', 'dark']
const themeIcons = { system: Monitor, light: Sun, dark: Moon }

function ThemeToggle() {
  const [theme, setThemeState] = useState(getTheme)
  const next = themeOrder[(themeOrder.indexOf(theme) + 1) % themeOrder.length]
  const Icon = themeIcons[theme]
  return (
    <button
      onClick={() => {
        setTheme(next)
        setThemeState(next)
      }}
      className="flex items-center hover:text-slate-800"
      title={`Theme: ${theme} (switch to ${next})`}
      aria-label={`Theme: ${theme}. Switch to ${next}`}
    >
      <Icon className="size-4" />
    </button>
  )
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  clsx(
    'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium',
    isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100',
  )

export function Layout() {
  const { me, signOut } = useAuth()
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-slate-200 bg-surface px-4">
        <span className="flex items-center gap-1.5 font-semibold text-slate-900">
          <Landmark className="size-5 text-indigo-600" />
          <span className="hidden sm:inline">Agency Knowledge Assistant</span>
        </span>
        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={linkClass}>
            <MessagesSquare className="size-4" /> Ask
          </NavLink>
          <NavLink to="/library" className={linkClass}>
            <FolderOpen className="size-4" /> Documents
          </NavLink>
          {me?.role === 'admin' && (
            <NavLink to="/admin" className={linkClass}>
              <Settings className="size-4" /> Admin
            </NavLink>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
          <span className="hidden sm:inline">{me?.email}</span>
          <ThemeToggle />
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
