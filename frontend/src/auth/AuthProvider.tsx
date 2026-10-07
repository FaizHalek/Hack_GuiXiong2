import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { get, login } from '../lib/api'
import { getToken, onTokenChange, setToken } from '../lib/session'
import type { Me } from '../lib/types'

interface AuthState {
  /** The access token, or null when signed out. */
  session: string | null
  sessionLoading: boolean
  me: Me | undefined
  meLoading: boolean
  meError: Error | null
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<string | null>(getToken)
  const queryClient = useQueryClient()

  useEffect(
    () =>
      onTokenChange((token) => {
        setSession(token)
        if (!token) queryClient.clear()
      }),
    [queryClient],
  )

  const meQuery = useQuery({
    queryKey: ['me', session],
    queryFn: () => get<Me>('/me'),
    enabled: !!session,
    staleTime: 60_000,
  })

  return (
    <AuthContext.Provider
      value={{
        session,
        sessionLoading: false,
        me: meQuery.data,
        meLoading: meQuery.isLoading,
        meError: meQuery.error,
        signIn: login,
        signOut: async () => setToken(null),
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
