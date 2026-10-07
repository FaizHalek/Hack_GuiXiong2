import { BookOpenCheck, FileSearch, Landmark, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { Button, Card, ErrorNote, Input } from '../components/ui'

const POINTS = [
  { Icon: FileSearch, text: 'Search policies, SOPs, circulars, guidelines, reports and minutes in plain language.' },
  { Icon: BookOpenCheck, text: 'Every answer cites the document and page it comes from.' },
  { Icon: ShieldCheck, text: 'You only see the collections your department has granted you.' },
]

export function Login() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await signIn(email, password)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-4">
      <div className="grid w-full max-w-3xl gap-6 md:grid-cols-[1fr_360px] md:items-center">
        <div className="hidden space-y-5 md:block">
          <div className="flex items-center gap-2 text-indigo-700 dark:text-indigo-400">
            <Landmark className="size-7" />
            <span className="text-xl font-semibold">Agency Knowledge Assistant</span>
          </div>
          <p className="text-slate-600">
            Turn your agency's documents into answers. Ask a question and get a cited answer drawn from official documents, instead
            of searching folders and shared drives.
          </p>
          <ul className="space-y-3">
            {POINTS.map(({ Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-sm text-slate-600">
                <Icon className="mt-0.5 size-4 shrink-0 text-indigo-600" />
                {text}
              </li>
            ))}
          </ul>
        </div>

        <Card className="w-full p-6">
          <div className="mb-1 flex items-center gap-2 md:hidden">
            <Landmark className="size-5 text-indigo-600" />
            <span className="font-semibold">Agency Knowledge Assistant</span>
          </div>
          <h1 className="text-lg font-semibold">Sign in</h1>
          <p className="mb-5 text-sm text-slate-500">Use the account your administrator created for you.</p>
          <form onSubmit={submit} className="space-y-3">
            <Input
              type="email"
              required
              autoComplete="username"
              placeholder="name@agency.gov"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Input
              type="password"
              required
              autoComplete="current-password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <ErrorNote error={error} />
            <Button type="submit" loading={loading} className="w-full">
              Sign in
            </Button>
          </form>
          <p className="mt-5 text-xs text-slate-400">
            Access is managed by your administrator. For the local demo, the seeded accounts are listed in{' '}
            <code>backend/.env.example</code>.
          </p>
        </Card>
      </div>
    </div>
  )
}
