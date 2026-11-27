import { useEffect, useState } from 'react'
import RevokeKeyButton from './RevokeKeyButton'

type Business = {
  id: string
  name: string
  email: string
  is_unlinked?: boolean
  active_live_keys: number
  active_test_keys: number
  requests_24h: number
  failed_requests_24h: number
  last_request_at: string | null
}

function lastRequestLabel(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 60_000))
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.floor(hours / 24)
  return `${days} ${days === 1 ? 'day' : 'days'} ago`
}
type BusinessKey = { id: string; name: string; environment: string; status: string }
type Access = { api_access_enabled: boolean; csrf_token: string }
type AccessFilter = 'all' | 'enabled' | 'disabled'

type PageProps = {
  disabled: boolean
  onViewRequests: (id: string) => void
}

async function read<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...options,
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(body?.error ?? `Request failed (${response.status}).`)
  }
  if (body === null) throw new Error('The server returned an invalid response.')
  return body as T
}

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function BusinessRow({ business, disabled, onViewRequests, accessFilter }: PageProps & {
  business: Business
  accessFilter: AccessFilter
}) {
  const [access, setAccess] = useState<Access | null>(null)
  const [accessError, setAccessError] = useState('')
  const [busy, setBusy] = useState(false)
  const root = `/dashboard-api/businesses/${encodeURIComponent(business.id)}`
  const accessUrl = `${root}/api-access/`

  useEffect(() => {
    const controller = new AbortController()
    read<Access>(accessUrl, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setAccess(value) })
      .catch(error => { if (!controller.signal.aborted) setAccessError(message(error)) })
    return () => controller.abort()
  }, [accessUrl])


  async function toggleAccess() {
    if (!access || busy) return
    const enabled = !access.api_access_enabled
    const effect = enabled
      ? 'Revoked keys will stay revoked.'
      : 'API keys for this business will stop authenticating while access is disabled.'
    const reason = window.prompt(
      `${enabled ? 'Enable' : 'Disable'} API access for ${business.name}?\n` +
      `${effect}\n\nReason (optional). Press OK to apply or Cancel to go back.`,
    )
    if (reason === null) return
    if (reason.trim().length > 500) {
      setAccessError('Use 500 characters or fewer for the reason.')
      return
    }

    setBusy(true)
    setAccessError('')
    try {
      const updated = await read<Omit<Access, 'csrf_token'>>(accessUrl, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': access.csrf_token,
        },
        body: JSON.stringify({ api_access_enabled: enabled, reason: reason.trim() }),
      })
      if (typeof updated.api_access_enabled !== 'boolean') {
        throw new Error('Unable to confirm the change. Reopen Businesses to check access.')
      }
      setAccess({ ...updated, csrf_token: access.csrf_token })
    } catch (error) {
      setAccessError(message(error))
    } finally {
      setBusy(false)
    }
  }

  const status = access
    ? (access.api_access_enabled ? 'enabled' : 'disabled')
    : null
  const hidden = accessFilter !== 'all' && accessFilter !== status

  return (
    <tr hidden={hidden}>
      <td>
        <button
          type="button"
          className="text-button"
          disabled={disabled}
          onClick={() => onViewRequests(business.id)}
        >
          <strong>{business.name}</strong>
        </button>
        {(business.email || business.is_unlinked) && (
          <small className="muted business-cell-detail">
            {business.is_unlinked ? business.id : business.email}
          </small>
        )}
      </td>
      <td>
        <span role="status" className={`business-access-badge business-access-${status ?? 'unknown'}`}>
          {status === 'enabled' ? 'Enabled'
            : status === 'disabled' ? 'Disabled'
            : accessError ? 'Unavailable' : 'Checking…'}
        </span>
      </td>
      <td>
        {business.active_live_keys.toLocaleString()} live
        {' · '}
        {business.active_test_keys.toLocaleString()} test
      </td>
      <td>
        <strong>{business.requests_24h.toLocaleString()}</strong>
        <small className="muted business-cell-detail">
          {business.failed_requests_24h.toLocaleString()} failed
        </small>
      </td>
      <td>
        {business.last_request_at ? (
          <time
            dateTime={business.last_request_at}
            title={new Date(business.last_request_at).toLocaleString()}
          >
            {lastRequestLabel(business.last_request_at)}
          </time>
        ) : 'Never'}
      </td>
      <td>
        <button
          type="button"
          className={status === 'enabled' ? 'danger-button' : 'primary-button'}
          disabled={disabled || !access || busy}
          aria-label={`${status === 'disabled' ? 'Enable' : 'Disable'} API access for ${business.name}`}
          onClick={() => void toggleAccess()}
        >
          {busy ? 'Saving…' : status === 'disabled' ? 'Enable API' : 'Disable API'}
        </button>
        {accessError && <p className="error-banner" role="alert">{accessError}</p>}
      </td>
    </tr>
  )
}

export default function BusinessesPage({ disabled, onViewRequests }: PageProps) {
  const [businesses, setBusinesses] = useState<Business[] | null>(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [accessFilter, setAccessFilter] = useState<AccessFilter>('all')

  useEffect(() => {
    const controller = new AbortController()
    read<{ businesses: Business[] }>('/dashboard-api/businesses/?include_inactive=1', {
      signal: controller.signal,
    })
      .then(value => {
        if (!Array.isArray(value.businesses)) throw new Error('The server did not return a business list.')
        if (!controller.signal.aborted) setBusinesses(value.businesses)
      })
      .catch(failure => { if (!controller.signal.aborted) setError(message(failure)) })
    return () => controller.abort()
  }, [])

  const query = search.trim().toLowerCase()
  const visible = businesses?.filter(business =>
    `${business.name} ${business.email} ${business.id}`.toLowerCase().includes(query),
  ) ?? []

  return (
    <section className="panel" aria-label="Business directory">
      <div className="table-toolbar">
        <input
          type="search"
          aria-label="Search businesses"
          placeholder="Search by name, email, or owner ID…"
          value={search}
          onChange={event => setSearch(event.target.value)}
        />
        <select
          aria-label="Filter businesses by API access"
          value={accessFilter}
          onChange={event => setAccessFilter(event.target.value as AccessFilter)}
        >
          <option value="all">All results</option>
          <option value="enabled">API enabled</option>
          <option value="disabled">API disabled</option>
        </select>
      </div>
      {error ? <p className="error-banner" role="alert">{error}</p>
        : !businesses ? <p className="empty" role="status">Loading businesses…</p>
        : visible.length === 0 ? (
          <p className="empty">{query ? 'No matching businesses.' : 'No businesses found.'}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Business</th>
                  <th scope="col">API access</th>
                  <th scope="col">Active keys</th>
                  <th scope="col">Requests (24h)</th>
                  <th scope="col">Last request</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody className="business-table-body">
                {visible.map(business => (
                  <BusinessRow
                    key={business.id}
                    business={business}
                    disabled={disabled}
                    onViewRequests={onViewRequests}
                    accessFilter={accessFilter}
                  />
                ))}
                <tr className="business-table-empty">
                  <td colSpan={6} className="empty">No businesses match this access filter.</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
    </section>
  )
}

type BusinessKeyMetadata = BusinessKey & {
  prefix: string
  created_at: string
  last_used_at: string | null
}

function formatKeyDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Never'
}

export function BusinessRequestKeys({
  businessId,
  onRevoked,
}: {
  businessId: string
  onRevoked?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [keys, setKeys] = useState<BusinessKeyMetadata[] | null>(null)
  const [keysError, setKeysError] = useState('')
  const [revokeId, setRevokeId] = useState<string | null>(null)
  const root = `/dashboard-api/businesses/${encodeURIComponent(businessId)}`

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    read<{ keys: BusinessKeyMetadata[] }>(`${root}/api-keys/`, {
      signal: controller.signal,
    })
      .then(value => {
        if (!Array.isArray(value.keys)) throw new Error('The server did not return a key list.')
        if (!controller.signal.aborted) setKeys(value.keys)
      })
      .catch(error => { if (!controller.signal.aborted) setKeysError(message(error)) })
    return () => controller.abort()
  }, [open, root])

  return (
    <section className="business-directory" aria-label="Business API keys">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => {
          setKeys(null)
          setKeysError('')
          setRevokeId(null)
          setOpen(!open)
        }}
      >
        {open ? 'Hide API keys' : 'Show API keys'}
      </button>
      {open && (
        <div className="business-directory-keys">
          <h3>API keys</h3>
          {keysError ? <p className="error-banner" role="alert">{keysError}</p>
            : !keys ? <p className="muted" role="status">Loading keys…</p>
            : keys.length === 0 ? <p className="muted">No API keys for this business.</p>
            : keys.map(key => (
              <div key={key.id} className="business-directory-key">
                <div className="business-directory-main">
                  <strong>{key.name} <span className="muted">· {key.environment} · {key.status}</span></strong>
                  {key.status !== 'revoked' && (
                    <button type="button" className="text-button"
                      aria-expanded={revokeId === key.id}
                      onClick={() => setRevokeId(revokeId === key.id ? null : key.id)}>
                      {revokeId === key.id ? 'Close' : 'Revoke…'}
                    </button>
                  )}
                </div>
                <p className="muted business-cell-detail">
                  <code>{key.prefix}</code>
                  {' · Created: '}{formatKeyDate(key.created_at)}
                  {' · Last used: '}{formatKeyDate(key.last_used_at)}
                </p>
                {revokeId === key.id && (
                  <RevokeKeyButton
                    key={key.id}
                    apiKey={{ ...key, business_owner_id: businessId }}
                    onRevoked={() => {
                      setKeys(current => current?.map(item =>
                        item.id === key.id ? { ...item, status: 'revoked' } : item,
                      ) ?? null)
                      setRevokeId(null)
                      onRevoked?.()
                    }}
                  />
                )}
              </div>
            ))}
        </div>
      )}
    </section>
  )
}
