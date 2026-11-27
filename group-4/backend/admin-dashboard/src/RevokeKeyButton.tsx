import { useRef, useState } from 'react'

type Props = {
  apiKey: {
    id: string
    name: string
    business_owner_id: string
    status: string
  }
  onRevoked: () => void
  promptOnClick?: boolean
}

export default function RevokeKeyButton({
  apiKey,
  onRevoked,
  promptOnClick = false,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reason, setReason] = useState('')
  const [completed, setCompleted] = useState(false)
  const submitting = useRef(false)

  async function revoke() {
    if (submitting.current || completed || apiKey.status === 'revoked') {
      return
    }

    let submittedReason = reason.trim()

    if (promptOnClick) {
      const entered = window.prompt(
        `Permanently revoke "${apiKey.name}"?\n\n` +
        'Applications using this key will lose access immediately. This cannot be undone.\n\n' +
        'Reason (optional). Click OK to revoke or Cancel to go back.',
      )
      if (entered === null) return
      submittedReason = entered.trim()
      if (submittedReason.length > 500) {
        setError('Use 500 characters or fewer for the reason.')
        return
      }
    } else {
      const confirmed = window.confirm(
        `Permanently revoke "${apiKey.name}"?\n\n` +
        'Applications using this key will lose API access immediately. ' +
        'This cannot be undone.',
      )

      if (!confirmed) return
    }

    submitting.current = true
    setBusy(true)
    setError('')

    try {
      // Obtain a fresh CSRF token using the current admin session.
      const tokenResponse = await fetch('/dashboard-api/overview/', {
        credentials: 'same-origin',
        cache: 'no-store',
      })

      if (!tokenResponse.ok) {
        throw new Error('Unable to verify your admin session. Sign in again.')
      }

      const tokenData = await tokenResponse.json() as {
        csrf_token?: string
      }

      if (!tokenData.csrf_token) {
        throw new Error(
          'The backend did not return a CSRF token. Check developer/views.py.',
        )
      }

      const response = await fetch(
        `/dashboard-api/businesses/${apiKey.business_owner_id}` +
        `/keys/${apiKey.id}/revoke/`,
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': tokenData.csrf_token,
          },
          body: JSON.stringify({ reason: submittedReason }),
        },
      )

      if (!response.ok) {
        if (response.status === 403) {
          throw new Error(
            'Permission or CSRF verification failed. Refresh and check your admin login.',
          )
        }

        if (response.status === 401) {
          throw new Error('Your admin session has expired. Sign in again.')
        }

        if (response.status === 409) {
          throw new Error(
            'This key is already revoked. Close this panel and refresh the dashboard.',
          )
        }

        if (response.status === 404) {
          throw new Error('This key was not found for the selected business.')
        }

        throw new Error(
          `Revocation was not confirmed (${response.status}). ` +
          'Refresh the dashboard and inspect the key status before retrying.',
        )
      }

      setCompleted(true)
      window.alert(`"${apiKey.name}" has been revoked.`)
      onRevoked()
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : 'Unable to confirm revocation. Refresh and check the key status.',
      )
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  if (apiKey.status === 'revoked') {
    return <p className="muted">This key is already revoked.</p>
  }

  if (promptOnClick) {
    return (
      <>
        <button
          type="button"
          className="danger-button"
          disabled={busy || completed}
          aria-label={`Revoke ${apiKey.name}`}
          onClick={() => void revoke()}
        >
          {completed ? 'Revoked' : busy ? 'Revoking…' : 'Revoke'}
        </button>
        {error && <p className="error-banner" role="alert">{error}</p>}
      </>
    )
  }

  return (
    <div className="revoke-section">
      <h3>Revoke API key</h3>

      <p className="muted">
        Permanently stops applications from using this key.
        Historical records remain available.
      </p>

      <label htmlFor="revocation-reason">Reason (optional)</label>
      <textarea
        id="revocation-reason"
        value={reason}
        onChange={event => setReason(event.target.value)}
        maxLength={500}
        rows={3}
        placeholder="For example: demonstration completed"
        disabled={busy || completed}
      />

      {error && (
        <p className="error-banner" role="alert">{error}</p>
      )}

      <button
        type="button"
        className="danger-button"
        disabled={busy || completed}
        onClick={() => void revoke()}
      >
        {completed ? 'Revoked' : busy ? 'Revoking…' : 'Revoke key'}
      </button>
    </div>
  )
}