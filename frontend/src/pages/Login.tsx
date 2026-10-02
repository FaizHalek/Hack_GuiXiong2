import { useState, type FormEvent } from 'react'
import { Button, Card, ErrorNote, Input } from '../components/ui'
import { supabase } from '../lib/supabase'

export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'password' | 'link'>('password')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    const { error } =
      mode === 'password'
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signInWithOtp({
            email,
            options: { emailRedirectTo: window.location.origin, shouldCreateUser: false },
          })
    setLoading(false)
    if (error) setError(error.message)
    else if (mode === 'link') setSent(true)
  }

  return (
    <div className="flex h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="text-lg font-semibold">Research Assistant</h1>
        <p className="mb-5 text-sm text-slate-500">Sign in to ask questions across your research libraries.</p>
        {sent ? (
          <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">
            Check {email} for a sign-in link.
          </p>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <Input type="email" required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            {mode === 'password' && (
              <Input
                type="password"
                required
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
            <ErrorNote error={error} />
            <Button type="submit" loading={loading} className="w-full">
              {mode === 'password' ? 'Sign in' : 'Email me a sign-in link'}
            </Button>
            <button
              type="button"
              className="w-full text-center text-sm text-indigo-600 hover:underline"
              onClick={() => setMode(mode === 'password' ? 'link' : 'password')}
            >
              {mode === 'password' ? 'Use a sign-in link instead' : 'Use a password instead'}
            </button>
          </form>
        )}
        <p className="mt-5 text-xs text-slate-400">Access is by invitation. Ask an administrator for an account.</p>
      </Card>
    </div>
  )
}
