import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { Layout } from './components/Layout'
import { Button, ErrorNote, Spinner } from './components/ui'
import { AdminLayout } from './pages/admin/AdminLayout'
import { Documents } from './pages/admin/Documents'
import { Insights } from './pages/admin/Insights'
import { Labels } from './pages/admin/Labels'
import { Users } from './pages/admin/Users'
import { Chat } from './pages/Chat'
import { Library } from './pages/Library'
import { Login } from './pages/Login'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function FullPageSpinner() {
  return (
    <div className="flex h-full items-center justify-center">
      <Spinner />
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, sessionLoading, me, meLoading, meError, signOut } = useAuth()
  if (sessionLoading) return <FullPageSpinner />
  if (!session) return <Navigate to="/login" replace />
  if (meLoading) return <FullPageSpinner />
  if (meError || !me) {
    return (
      <div className="mx-auto mt-20 max-w-md space-y-3 p-4">
        <ErrorNote error={meError ?? 'Could not load your profile.'} />
        <Button variant="secondary" onClick={signOut}>
          Sign out
        </Button>
      </div>
    )
  }
  return <>{children}</>
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  return me?.role === 'admin' ? <>{children}</> : <Navigate to="/" replace />
}

function LoginRoute() {
  const { session, sessionLoading } = useAuth()
  if (sessionLoading) return <FullPageSpinner />
  return session ? <Navigate to="/" replace /> : <Login />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginRoute />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<Chat />} />
              <Route path="library" element={<Library />} />
              <Route
                path="admin"
                element={
                  <RequireAdmin>
                    <AdminLayout />
                  </RequireAdmin>
                }
              >
                <Route index element={<Insights />} />
                <Route path="documents" element={<Documents />} />
                <Route path="labels" element={<Labels />} />
                <Route path="users" element={<Users />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
