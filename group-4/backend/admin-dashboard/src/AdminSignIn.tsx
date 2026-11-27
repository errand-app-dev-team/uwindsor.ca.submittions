import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'

export const ADMIN_SESSION_EXPIRED = 'aerrand:admin-session-expired'
const authPath = '/dashboard-api/dashboard-auth/'

function api(path: string, options?: RequestInit) {
  return fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options })
}

async function authPost(action: 'login' | 'logout', body?: object) {
  const csrf = await api(`${authPath}csrf/`)
  const cookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='))
  if (!csrf.ok || !cookie) {
    throw new Error('Could not start a secure session. Check that Django is running and cookies are enabled.')
  }

  return api(`${authPath}${action}/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': decodeURIComponent(cookie.slice('csrftoken='.length)),
    },
    body: JSON.stringify(body ?? {}),
  })
}

async function checkAdmin(signal?: AbortSignal) {
  const response = await api('/dashboard-api/overview/', { signal })
  if (response.status === 401) return 'signed-out'
  if (response.status === 403) return 'denied'
  if (!response.ok) throw new Error('Could not connect to the admin API. Check that Django is running.')
  return 'admin'
}

export default function AdminSignIn({ children }: {
  children: (signOut: () => void, signingOut: boolean) => ReactNode
}) {
  const [state, setState] = useState<'checking' | 'signed-out' | 'denied' | 'admin'>('checking')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [password, setPassword] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    function onExpired() {
      setError('Your session expired. Please sign in again.')
      setState('signed-out')
    }

    window.addEventListener(ADMIN_SESSION_EXPIRED, onExpired)
    void checkAdmin(controller.signal).then(result => {
      if (!controller.signal.aborted) setState(result)
    }).catch(() => {
      if (!controller.signal.aborted) {
        setError('Could not connect to the admin API. Check that Django is running.')
        setState('signed-out')
      }
    })

    return () => {
      controller.abort()
      window.removeEventListener(ADMIN_SESSION_EXPIRED, onExpired)
    }
  }, [])

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const username = new FormData(event.currentTarget).get('username')
    setBusy(true)
    setError('')
    try {
      const response = await authPost('login', { username, password })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.error ?? 'Sign-in failed. Check your credentials and Django settings.')
      }
      const result = await checkAdmin()
      setState(result)
      if (result === 'signed-out') setError('Sign-in did not establish a session. Check your cookie settings.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setPassword('')
      setBusy(false)
    }
  }

  async function signOut() {
    setBusy(true)
    setError('')
    try {
      const response = await authPost('logout')
      if (!response.ok) throw new Error('Could not sign out. Please try again.')
      setState('signed-out')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign out. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'checking') {
    return (
      <main className="admin-auth">
        <p className="admin-auth-brand" role="status">Loading dashboard…</p>
      </main>
    )
  }

  if (state === 'admin') {
    return (
      <>
        {error && <p className="admin-auth-notice" role="alert">{error}</p>}
        {children(() => { void signOut() }, busy)}
      </>
    )
  }

  return (
    <main className="admin-auth">
      <section className="admin-auth-card" aria-labelledby="admin-auth-title">
        <p className="admin-auth-brand">Aerrand · Admin Console</p>
        <h1 id="admin-auth-title">Sign in to Aerrand</h1>
        {(
          <>
            <p>{state === 'denied'
              ? 'This account does not have administrator access. Sign in with an administrator account.'
              : 'Use your administrator credentials to open the dashboard.'}</p>
            <form onSubmit={signIn}>
              <label htmlFor="admin-username">Username</label>
              <input id="admin-username" name="username" autoComplete="username" required disabled={busy} />
              <label htmlFor="admin-password">Password</label>
              <input id="admin-password" name="password" type="password" autoComplete="current-password"
                value={password} onChange={event => setPassword(event.target.value)} required disabled={busy} />
              {error && <p role="alert">{error}</p>}
              <button type="submit" className="primary-button" disabled={busy}>
                {busy ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </>
        )}
      </section>
    </main>
  )
}
