import { useEffect, useRef, useState } from 'react'
import './App.css'
import AdminSignIn, { ADMIN_SESSION_EXPIRED } from './AdminSignIn'
import BusinessesPage, { BusinessRequestKeys } from './BusinessesPage'
import RequestTrends from './RequestTrends'
import RevokeKeyButton from './RevokeKeyButton'
import BusinessApiAccessPanel from './BusinessApiAccessPanel'

type ApiKey = {
  business_name?: string | null
  id: string
  name: string
  business_owner_id: string
  prefix: string
  environment: string
  scopes: string[]
  status: string
  created_at: string
  expires_at: string | null
  last_used_at: string | null
}

type RequestLog = {
  business_name?: string | null
  request_id: string
  api_key_id: string
  business_owner_id: string
  method: string
  path: string
  status: number
  duration_ms: number
  error_code: string | null
  created_at: string
}

type SecurityEvent = {
  business_name?: string | null
  action: string
  business_owner_id: string
  actor_id: string
  target_id: string
  timestamp: string
}

type DashboardData = {
  generated_at: string
  record_limit: number
  business_owner_id: string | null
  api_key_id: string | null
  summary: {
    requests_last_24h: number
    api_deliveries: {
      pk: string
      business_owner_id: string
      environment: string
      booking_id: string
      batch_id: string
      stop_ids: string[]
      external_reference: string
      created_at: string
    }[]
    webhook_failure_rate_last_24h: number | null
    webhook_completed_last_24h: number | null
    webhook_delivered_last_24h: number | null
    webhook_failed_last_24h: number | null
    top_businesses_last_24h: {
      business_owner_id: string
      business_name: string | null
      request_count: number
    }[]
    total_keys: number
    active_keys: number
    total_requests: number
    failed_requests: number
    api_bookings_last_24h: number
  }
  keys: ApiKey[]
  requests: RequestLog[]
  security_events: SecurityEvent[]
}

type Page =
  | 'Overview'
  | 'Businesses'
  | 'API keys'
  | 'Request activity'
  | 'API deliveries'
  | 'Security events'

type Detail = {
  title: string
  fields: [string, string][]
  apiKey?: ApiKey
}

const pages: Page[] = [
  'Overview',
  'Businesses',
  'API keys',
  'Request activity',
  'API deliveries',
  'Security events',
]

function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Not recorded'
}

function eventName(action: string) {
  const names: Record<string, string> = {
    'key.created': 'API key created',
    'key.revoked': 'API key revoked',
    'key.rotated': 'API key rotated',
    'business.api_access_enabled': 'Business API access enabled',
    'business.api_access_disabled': 'Business API access disabled',
  }
  return names[action] ?? action
}

function result(status: number) {
  if (status >= 200 && status < 300) return 'Successful'
  if (status >= 400 && status < 500) return 'Request rejected'
  if (status >= 500) return 'Server error'
  return 'Other response'
}

function errorName(code: string | null) {
  const names: Record<string, string> = {
    validation_error: 'Invalid or missing information',
    insufficient_scope: 'Key lacks the required permission',
    invalid_api_key: 'Invalid, expired, or inactive key',
    business_api_access_disabled: 'Business API access is disabled',

  }
  return code ? names[code] ?? code : 'No error recorded'
}

async function fetchDashboard(
  businessId: string,
  signal: AbortSignal,
  apiKeyId = '',
): Promise<DashboardData> {
  const query = new URLSearchParams()

  if (businessId.trim()) {
    query.set('business_owner_id', businessId.trim())
  }

  if (apiKeyId) {
    query.set('api_key_id', apiKeyId)
  }

  const response = await fetch(`/dashboard-api/overview/?${query}`, {
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
  })

  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event(ADMIN_SESSION_EXPIRED))
      throw new Error('Your session expired. Please sign in again.')
    }
    if (response.status === 403) {
      throw new Error('An active superuser account is required.')
    }
    if (response.status === 400) {
      throw new Error('Enter a valid business UUID, or choose All businesses.')
    }
    if (response.status === 404) {
      throw new Error('API key not found in the selected business scope.')
    }
    throw new Error(`Unable to load dashboard (${response.status}).`)
  }

  return await response.json() as DashboardData
}

export default function App() {
  return (
    <AdminSignIn>
      {(signOut, signingOut) => <Dashboard signOut={signOut} signingOut={signingOut} />}
    </AdminSignIn>
  )
}

function Dashboard({ signOut, signingOut }: {
  signOut: () => void
  signingOut: boolean
}) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [page, setPage] = useState<Page>(() => {
    const saved = sessionStorage.getItem('aerrand.admin.page')
    switch (saved) {
      case 'Overview':
      case 'Businesses':
      case 'API keys':
      case 'Request activity':
      case 'API deliveries':
      case 'Security events':
        return saved
      default:
        return 'Overview'
    }
  })

  useEffect(() => {
    sessionStorage.setItem('aerrand.admin.page', page)
  }, [page])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [businessInput, setBusinessInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const pendingRequest = useRef<AbortController | null>(null)
  const [filterBusinesses, setFilterBusinesses] = useState<
    { id: string; name: string; email: string; is_unlinked?: boolean }[]
  >([])
  const [businessLookupError, setBusinessLookupError] = useState('')
  const [businessFilterError, setBusinessFilterError] = useState('')
  const hasDashboard = data !== null

  useEffect(() => {
    if (!hasDashboard) return
    const controller = new AbortController()

    async function loadBusinessChoices() {
      try {
        const response = await fetch('/dashboard-api/businesses/?include_inactive=1', {
          credentials: 'same-origin',
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Could not load businesses.')
        const result = await response.json()
        if (!Array.isArray(result.businesses)) throw new Error('Invalid business list.')
        if (!controller.signal.aborted) {
          setFilterBusinesses(result.businesses)
          setBusinessLookupError('')
        }
      } catch {
        if (!controller.signal.aborted) {
          setBusinessLookupError('Business names and emails are unavailable. You can still enter an owner ID.')
        }
      }
    }

    void loadBusinessChoices()
    return () => controller.abort()
  }, [hasDashboard])

  const appliedBusinessId = data?.business_owner_id ?? ''
  const appliedBusiness = filterBusinesses.find(business => business.id === appliedBusinessId)
  const query = businessInput.trim().toLowerCase()
  const businessMatches = query
    ? filterBusinesses.filter(business =>
        [business.name, business.email, business.id]
          .some(value => value.toLowerCase().includes(query)),
      )
    : []

  function applyBusiness(id: string) {
    setBusinessFilterError('')
    void load(id, '')
  }

  useEffect(() => {
    const controller = new AbortController()
    pendingRequest.current = controller

    async function initialize() {
      try {
        const dashboard = await fetchDashboard('', controller.signal)
        if (!controller.signal.aborted) setData(dashboard)
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(
            failure instanceof Error ? failure.message : 'Unable to connect.',
          )
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    void initialize()
    return () => pendingRequest.current?.abort()
  }, [])

  async function load(
    businessId: string = data?.business_owner_id ?? '',
    apiKeyId: string = data?.api_key_id ?? '',
    nextPage?: Page,
  ) {
    pendingRequest.current?.abort()
    const controller = new AbortController()
    pendingRequest.current = controller

    setLoading(true)
    setError('')
    setDetail(null)

    try {
      const dashboard = await fetchDashboard(
        businessId,
        controller.signal,
        apiKeyId,
      )

      if (!controller.signal.aborted) {
        setData(dashboard)
        setBusinessInput(dashboard.business_owner_id ?? '')
        setSearch('')
        setFilter('all')
        if (nextPage) setPage(nextPage)
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(
          failure instanceof Error ? failure.message : 'Unable to connect.',
        )
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  function navigate(nextPage: Page, nextFilter = 'all') {
    setPage(nextPage)
    setSearch('')
    setFilter(nextFilter)
    setDetail(null)
  }

  function matches(...values: unknown[]) {
    return values.join(' ').toLowerCase().includes(search.toLowerCase())
  }

  const keys = data?.keys ?? []
  const requests = data?.requests ?? []
  const events = data?.security_events ?? []

  const visibleKeys = keys.filter(key =>
    matches(
      key.name, key.prefix, key.business_name ?? '', key.business_owner_id, key.scopes.join(' '),
    ) && (filter === 'all' || key.status === filter),
  )

  const dashboardTime = data ? Date.parse(data.generated_at) : Date.now()
  const recentCutoff = dashboardTime - 24 * 60 * 60 * 1000

  const visibleRequests = requests.filter(request =>
    matches(
      request.request_id, request.business_name ?? '', request.business_owner_id, request.api_key_id,
      request.method, request.path, request.status, request.error_code,
    ) && (
      filter === 'all' ||
      (filter === 'recent' &&
        Date.parse(request.created_at) >= recentCutoff &&
        Date.parse(request.created_at) <= dashboardTime) ||
      (filter === 'success' && request.status >= 200 && request.status < 300) ||
      (filter === 'error' && request.status >= 400)
    ),
  )

  const visibleEvents = events.filter(event =>
    matches(
      eventName(event.action), event.business_name ?? '', event.business_owner_id,
      event.actor_id, event.target_id,
    ) && (filter === 'all' || event.action === filter),
  )

  const successful = requests.filter(
    request => request.status >= 200 && request.status < 300,
  ).length
  const rejected = requests.filter(request => request.status >= 400).length

  function inspectKey(key: ApiKey) {
    setDetail({
      title: key.name,
      apiKey: key,
      fields: [
        ['Key ID', key.id],
        ['Business', key.business_name || 'Unknown business'],
        ['Business owner ID', key.business_owner_id],
        ['Safe prefix', key.prefix],
        ['Environment', key.environment],
        ['Permissions', key.scopes.join(', ') || 'None'],
        ['Status', key.status],
        ['Created', date(key.created_at)],
        ['Expires', key.expires_at ? date(key.expires_at) : 'No expiry'],
        ['Last used', date(key.last_used_at)],
      ],
    })
  }

  function inspectRequest(request: RequestLog) {
    setDetail({
      title: `${request.method} ${request.path}`,
      fields: [
        ['Request ID', request.request_id],
        ['Business owner ID', request.business_owner_id],
        ['API key ID', request.api_key_id],
        ['Time', date(request.created_at)],
        ['Result', `${result(request.status)} (${request.status})`],
        ['Response time', `${request.duration_ms} ms`],
        ['Error', errorName(request.error_code)],
      ],
    })
  }

  function inspectEvent(event: SecurityEvent) {
    setDetail({
      title: eventName(event.action),
      fields: [
        ['Event', event.action],
        ['Business', event.business_name || 'Unknown business'],
        ['Business owner ID', event.business_owner_id],
        ['Actor ID', event.actor_id],
        ['Target ID', event.target_id],
        ['Time', date(event.timestamp)],
      ],
    })
  }

  function openHistory(key: ApiKey, destination: Page) {
    setBusinessInput(key.business_owner_id)
    void load(key.business_owner_id, key.id, destination)
  }

  function requestTable(rows: RequestLog[], showError = false) {
    return (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              {showError && <th>Business</th>}
              <th>Request</th>
              <th>Result</th>
              <th>Response time</th>
              {showError && <th>Error</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(request => (
              <tr key={request.request_id}>
                <td>{date(request.created_at)}</td>
                {showError && (
                  <td>
                    {request.business_name ? (
                      <strong>{request.business_name}</strong>
                    ) : (
                      <>
                        <span>Unknown business</span>
                        {request.business_owner_id && (
                          <small className="muted business-cell-detail">
                            {request.business_owner_id}
                          </small>
                        )}
                      </>
                    )}
                  </td>
                )}
                <td>
                  <button
                    className="record-link"
                    onClick={() => inspectRequest(request)}
                  >
                    {request.method} {request.path}
                  </button>
                </td>
                <td>
                  <span className={`badge ${request.status >= 400 ? 'bad' : 'neutral'}`}>
                    {result(request.status)} ({request.status})
                  </span>
                </td>
                <td>{request.duration_ms} ms</td>
                {showError && <td>{errorName(request.error_code)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p className="empty">No matching requests recorded.</p>}
      </div>
    )
  }

  return (
    <div className="dashboard">
      <aside className="sidebar">
        <a className="brand" href="/">
          aerrand<span>ADMIN CONSOLE</span>
        </a>
        <p className="nav-heading">API MANAGEMENT</p>
        <nav aria-label="Main navigation">
          {pages.map((item, index) => (
            <button
              key={item}
              className={page === item ? 'nav-item selected' : 'nav-item'}
              onClick={() => navigate(item)}
              aria-current={page === item ? 'page' : undefined}
            >
              <span className="nav-number">0{index + 1}</span>
              {item}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="session-dot" />
          {data ? 'Administrator data loaded' : 'Administrator console'}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <span>Workspace <span className="muted">/ {page}</span></span>
          <div className="admin-topbar-actions">
            <span className="admin-label">Aerrand administration</span>
            <button type="button" className="admin-signout-button"
              onClick={signOut} disabled={signingOut} aria-busy={signingOut}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"
                strokeLinejoin="round" aria-hidden="true" focusable="false">
                <path d="M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5M9 12h11m-4-4 4 4-4 4" />
              </svg>
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        </header>

        <div className="content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">DEVELOPER API</p>
              <h1>{page}</h1>
              <p className="muted">
                Manage access and understand your partner API activity.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={() => void load()}
              disabled={loading}
            >
              {loading ? 'Refreshing…' : '↻ Refresh data'}
            </button>
          </div>

          {error && (
            <div className="error-banner" role="alert">
              {error}
              {data && ' Previously loaded data remains displayed.'}
              {' '}
              <a href="http://127.0.0.1:8001/admin/login/">Sign in ↗</a>
            </div>
          )}

          {!data && loading && <p role="status">Loading database records…</p>}

          {data && (
            <>
              {page !== 'Businesses' && (
                <form
                  className="business-filter"
                  onSubmit={event => {
                    event.preventDefault()
                    if (!query) {
                      applyBusiness('')
                      return
                    }
                    if (/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(query)) {
                      applyBusiness(query)
                      return
                    }
                    const exact = businessMatches.filter(business =>
                      [business.name, business.email].some(value => value.toLowerCase() === query),
                    )
                    const choices = exact.length ? exact : businessMatches
                    if (choices.length === 1) {
                      applyBusiness(choices[0].id)
                    } else {
                      setBusinessFilterError(choices.length
                        ? 'More than one business matches. Select one below.'
                        : 'No matching business. Try a different name, email, or owner ID.')
                    }
                  }}
                >
                  <label htmlFor="business-id">Business</label>
                  <div className="business-filter-controls">
                    <input
                      id="business-id"
                      type="search"
                      placeholder="Search by name, email, or owner ID…"
                      value={appliedBusiness && !appliedBusiness.is_unlinked && businessInput === appliedBusinessId
                        ? appliedBusiness.name
                        : businessInput}
                      onChange={event => {
                        setBusinessInput(event.target.value)
                        setBusinessFilterError('')
                      }}
                      disabled={loading}
                    />
                    <button type="submit" className="primary-button" disabled={loading}>
                      Apply filter
                    </button>
                    <button type="button" className="close-button" disabled={loading}
                      onClick={() => applyBusiness('')}>
                      All businesses
                    </button>
                  </div>
                  {businessLookupError && <p className="muted">{businessLookupError}</p>}
                  {businessFilterError && <p role="alert">{businessFilterError}</p>}
                  {query !== appliedBusinessId.toLowerCase() && businessMatches.length > 0 && (
                    <ul className="business-search-results" aria-label="Matching businesses">
                      {businessMatches.map(business => (
                        <li key={business.id}>
                          <button type="button" className="text-button" disabled={loading}
                            onClick={() => applyBusiness(business.id)}>
                            <strong>{business.name}</strong>
                            <span>{business.email || business.id}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </form>
              )}

              {page === 'Overview' && data.business_owner_id && (
                <details className="panel business-settings">
                  <summary>
                    <span>
                      <strong>Business API settings</strong>
                      <small>Manage access, API keys, rate limits, and daily quotas</small>
                    </span>
                    <span className="business-settings-chevron" aria-hidden="true" />
                  </summary>
                  <BusinessApiAccessPanel
                  key={`${data.business_owner_id}-${data.generated_at}`}
                  businessId={data.business_owner_id}
                  disabled={loading}
                  onChanged={() => {
                    void load(
                      data.business_owner_id ?? '',
                      '',
                      'Security events',
                    )
                  }}
                />
                  <BusinessRequestKeys
                    key={data.business_owner_id}
                    businessId={data.business_owner_id}
                    onRevoked={() => { void load() }}
                  />
                </details>
              )}

              {page !== 'Businesses' && data.api_key_id && (
                <div className="integration-note" style={{ marginBottom: 20 }}>
                  <strong>Showing history for one API key</strong>
                  <p className="identifier">
                    {keys[0]?.name ?? 'Selected key'} · {data.api_key_id}
                  </p>
                  <button
                    className="text-button"
                    disabled={loading}
                    onClick={() => void load(data.business_owner_id ?? '', '')}
                  >
                    Clear key filter
                  </button>
                </div>
              )}

              {(page === 'API keys' || page === 'Request activity') && (
                <p className="muted">
                  {page === 'API keys'
                    ? `${data.summary.total_keys} total keys · ${data.summary.active_keys} active`
                    : `${data.summary.total_requests} recorded requests · ${data.summary.failed_requests} failed across all time`}
                </p>
              )}

              <div className="data-note">
                <span>
                  {page === 'Businesses'
                    ? 'Select a business to view its request activity and manage its API keys. Request totals include live and test traffic.'
                    : `Cards show totals for the selected business and key filters. Tables show the latest ${data.record_limit} records maximum per section, including test records.`}
                </span>
                <span>Updated {date(data.generated_at)}</span>
              </div>

              {page === 'API deliveries' ? (
                data.api_key_id ? (
                  <section className="panel overview-detail-panel">
                    <h2>API delivery history</h2>
                    <p className="muted">
                      Clear the API key filter above to view delivery history by business.
                    </p>
                  </section>
                ) : (
                  <section className="panel overview-detail-panel">
                    <h2>API delivery history</h2>
                    <p className="muted">
                      Latest 100 API bookings for the selected business scope. Live status is not shown.
                    </p>
                    {!data.summary.api_deliveries?.length ? (
                      <p className="muted overview-empty-state">No bookings yet. Confirmed API bookings will appear here.</p>
                    ) : (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Created</th><th>Business</th><th>Environment</th>
                              <th>Booking details</th>
                              <th>External reference</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.summary.api_deliveries.map(delivery => (
                              <tr key={delivery.pk}>
                                <td>{date(delivery.created_at)}</td>
                                <td>
                                  <strong>
                                    {filterBusinesses.find(business => business.id === delivery.business_owner_id)?.name || 'Unknown business'}
                                  </strong>
                                  <small className="delivery-business-id">
                                    {delivery.business_owner_id}
                                  </small>
                                </td>
                                <td>
                                  <span className={`delivery-environment ${delivery.environment === 'live' ? 'is-live' : 'is-test'}`}>
                                    {delivery.environment === 'live' ? 'Live' : 'Test'}
                                  </span>
                                </td>
                                <td>
                                  {delivery.booking_id && (
                                    <div className="delivery-identifier">
                                      <small>Booking</small>
                                      <strong>{delivery.booking_id}</strong>
                                    </div>
                                  )}
                                  {delivery.batch_id && (
                                    <div className="delivery-identifier">
                                      <small>Batch</small>
                                      <strong>{delivery.batch_id}</strong>
                                    </div>
                                  )}
                                  {!delivery.booking_id && !delivery.batch_id && '—'}
                                  {delivery.stop_ids.length > 0 && (
                                    <details>
                                      <summary>Stop IDs</summary>
                                      {delivery.stop_ids.join(', ')}
                                    </details>
                                  )}
                                </td>
                                <td>{delivery.external_reference || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                )
              ) : page === 'Businesses' ? (
                <BusinessesPage
                  disabled={loading}
                  onViewRequests={id => {
                    setBusinessInput(id)
                    setBusinessFilterError('')
                    void load(id, '', 'Overview')
                  }}
                />
              ) : page === 'Overview' ? (
                <>
                  <section className="stats" aria-label="Dashboard summary">
                    <button
                      className="stat-card mint"
                      onClick={() => navigate('API keys')}
                    >
                      <span>Total keys</span>
                      <strong>{data.summary.total_keys}</strong>
                      <small>Explore records ↗</small>
                    </button>
                    <button
                      className="stat-card blue"
                      onClick={() => navigate('API keys', 'active')}
                    >
                      <span>Active keys</span>
                      <strong>{data.summary.active_keys}</strong>
                      <small>Explore records ↗</small>
                    </button>
                    <button
                      className="stat-card lavender"
                      onClick={() => navigate('Request activity')}
                    >
                      <span>Total recorded requests</span>
                      <strong>{data.summary.total_requests}</strong>
                      <small>Explore records ↗</small>
                    </button>
                    <button
                      className="stat-card peach"
                      onClick={() => navigate('Request activity', 'error')}
                    >
                      <span>Failed recorded requests</span>
                      <strong>{data.summary.failed_requests}</strong>
                      <small>Explore records ↗</small>
                    </button>
                    <button
                      className="stat-card yellow"
                      onClick={() => navigate('Request activity', 'recent')}
                    >
                      <span>Requests in the last 24 hours</span>
                      <strong>{data.summary.requests_last_24h}</strong>
                      <small>Explore records ↗</small>
                    </button>
                    <button
                      className="stat-card lavender"
                      onClick={() => navigate('API deliveries')}
                    >
                      <span>API bookings in the last 24 hours</span>
                      <strong>{data.summary.api_bookings_last_24h}</strong>
                      <small>View delivery history ↗</small>
                    </button>
                    {!data.api_key_id && (
                      <div className="stat-card blue">
                        <span>Webhook failure rate · Last 24 hours</span>
                        <strong>
                          {data.summary.webhook_failure_rate_last_24h == null
                            ? '—'
                            : `${data.summary.webhook_failure_rate_last_24h}%`}
                        </strong>
                        <div className="webhook-metric-details">
                          {data.summary.webhook_completed_last_24h == null ? (
                            <small>Delivery counts unavailable</small>
                          ) : (
                            <>
                              <small>
                                Completed: {data.summary.webhook_completed_last_24h}
                              </small>
                              <div className="webhook-metric-breakdown">
                                <span className="webhook-delivered">
                                  <i aria-hidden="true" />
                                  Delivered: {data.summary.webhook_delivered_last_24h}
                                </span>
                                <span className="webhook-failed">
                                  <i aria-hidden="true" />
                                  Failed: {data.summary.webhook_failed_last_24h}
                                </span>
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                  </section>

                  <div className="overview-activity-layout">
                    <div className="overview-chart">
                      <div className="overview-chart-actions">
                        <button type="button" className="text-button" onClick={() => navigate('Request activity')}>
                          View request activity ↗
                        </button>
                      </div>
                      <RequestTrends
                        key={data.generated_at}
                        businessId={data.business_owner_id ?? ''}
                        apiKeyId={data.api_key_id ?? ''}
                      />
                    </div>
                    {!data.business_owner_id && !data.api_key_id && (
                      <section className="panel overview-detail-panel" id="top-businesses-detail">
                        <p className="overview-kicker">LAST 24 HOURS</p>
                        <h2>Top businesses by API requests</h2>
                        {data.summary.top_businesses_last_24h.length === 0 ? (
                          <p className="muted overview-empty-state">No business requests in this period.</p>
                        ) : (
                          <ol>
                            {data.summary.top_businesses_last_24h.map(business => (
                              <li key={business.business_owner_id}>
                                <button
                                type="button"
                                className="text-button"
                                disabled={loading}
                                onClick={() => {
                                  setBusinessInput(business.business_owner_id)
                                  setBusinessFilterError('')
                                  void load(business.business_owner_id, '', 'Overview')
                                }}
                              >
                                <strong>{business.business_name ?? business.business_owner_id}</strong>
                                <span aria-hidden="true"> ›</span>
                              </button>
                                <span className="overview-rank-count">
                                  {business.request_count.toLocaleString()} {business.request_count === 1 ? 'request' : 'requests'}
                                </span>
                              </li>
                            ))}
                          </ol>
                        )}
                      </section>
                    )}
                  </div>

                  <div className="overview-grid">
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Request outcomes</h2>
                          <p className="muted">
                            Among the requests currently loaded
                          </p>
                        </div>
                      </div>
                      {requests.length ? (
                        <div className="outcomes">
                          {[
                            ['Successful', successful, 'green'],
                            ['Failed', rejected, 'red'],
                            ['Other', requests.length - successful - rejected, 'grey'],
                          ].map(([label, count, color]) => (
                            <div className="outcome-row" key={String(label)}>
                              <div>
                                <span>{label}</span><strong>{count}</strong>
                              </div>
                              <div className="bar-track">
                                <div
                                  className={`bar-fill ${color}`}
                                  style={{
                                    width: `${Number(count) / requests.length * 100}%`,
                                  }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="empty">No authenticated requests recorded.</p>
                      )}
                    </section>

                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Security activity</h2>
                          <p className="muted">Latest recorded security events</p>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => navigate('Security events')}
                        >
                          View all →
                        </button>
                      </div>
                      {events.slice(0, 4).map((event, index) => (
                        <div className="event-row" key={`${event.target_id}-${index}`}>
                          <span className="event-icon">↗</span>
                          <div>
                            <button
                              className="record-link"
                              onClick={() => inspectEvent(event)}
                            >
                              {eventName(event.action)}
                            </button>
                            <small>{date(event.timestamp)}</small>
                          </div>
                        </div>
                      ))}
                      {!events.length && (
                        <p className="empty">No security events recorded.</p>
                      )}
                    </section>
                  </div>


                </>
              ) : (
                <section className="panel">
                  <div className="table-toolbar">
                    <input
                      aria-label={`Search ${page}`}
                      placeholder={`Search ${page.toLowerCase()}…`}
                      value={search}
                      onChange={event => setSearch(event.target.value)}
                    />
                    <select
                      aria-label={`Filter ${page}`}
                      value={filter}
                      onChange={event => setFilter(event.target.value)}
                    >
                      <option value="all">All results</option>
                      {page === 'API keys' && (
                        <>
                          <option value="active">Active</option>
                          <option value="expired">Expired</option>
                          <option value="revoked">Revoked</option>
                          <option value="rotating">Rotating</option>
                        </>
                      )}
                      {page === 'Request activity' && (
                        <>
                          <option value="recent">Last 24 hours</option>
                          <option value="success">Successful</option>
                          <option value="error">Failed</option>
                        </>
                      )}
                      {page === 'Security events' && (
                        <>
                          <option value="key.created">Key created</option>
                          <option value="key.revoked">Key revoked</option>
                          <option value="key.rotated">Key rotated</option>
                          <option value="business.api_access_enabled">
                            Business access enabled
                          </option>
                          <option value="business.api_access_disabled">
                            Business access disabled
                          </option>
                        </>
                      )}
                    </select>
                  </div>

                  {page === 'Request activity' && data.business_owner_id && (
                    <div className="table-toolbar">
                      <button
                        type="button"
                        className="text-button"
                        disabled={loading}
                        onClick={() => void load(data.business_owner_id ?? '', '', 'API keys')}
                      >
                        View business API keys ↗
                      </button>
                    </div>
                  )}
                  {page === 'Request activity' && requestTable(visibleRequests, true)}

                  {page === 'API keys' && (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Name / prefix</th><th scope="col">Business</th><th>Environment</th>
                            <th>Permissions</th><th>Status</th><th>Expires</th><th scope="col">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleKeys.map(key => (
                            <tr key={key.id}>
                              <td>
                                <button
                                  className="record-link"
                                  onClick={() => inspectKey(key)}
                                >
                                  {key.name}
                                </button>
                                <small className="cell-subtext">{key.prefix}</small>
                              </td>
                              <td>{key.business_name || 'Unknown business'}</td>
                              <td>
                                <span className="badge neutral">{key.environment}</span>
                              </td>
                              <td>{key.scopes.join(', ') || 'None'}</td>
                              <td>
                                <span className={`badge ${key.status === 'active' ? 'good' : 'warning'}`}>
                                  {key.status}
                                </span>
                              </td>
                              <td>
                                {key.expires_at ? date(key.expires_at) : 'No expiry'}
                              </td>
                              <td>
                                {key.status === 'active' || key.status === 'rotating' ? (
                                  <RevokeKeyButton
                                    apiKey={key}
                                    promptOnClick
                                    onRevoked={() => { void load() }}
                                  />
                                ) : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!visibleKeys.length && (
                        <p className="empty">No matching keys recorded.</p>
                      )}
                    </div>
                  )}

                  {page === 'Security events' && (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr><th>Event</th><th>Time</th><th scope="col">Business</th><th>Target ID</th></tr>
                        </thead>
                        <tbody>
                          {visibleEvents.map((event, index) => (
                            <tr key={`${event.target_id}-${event.timestamp}-${index}`}>
                              <td>
                                <button
                                  className="record-link"
                                  onClick={() => inspectEvent(event)}
                                >
                                  {eventName(event.action)}
                                </button>
                              </td>
                              <td>{date(event.timestamp)}</td>
                              <td>{event.business_name || 'Unknown business'}</td>
                              <td className="identifier">{event.target_id}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!visibleEvents.length && (
                        <p className="empty">No matching security events recorded.</p>
                      )}
                    </div>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </main>

      {detail && (
        <div className="modal-backdrop">
          <section
            className="detail-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="detail-title"
            onKeyDown={event => {
              if (event.key === 'Escape') setDetail(null)
            }}
          >
            <div className="panel-heading">
              <h2 id="detail-title">{detail.title}</h2>
              <button
                className="close-button"
                autoFocus
                onClick={() => setDetail(null)}
              >
                Close
              </button>
            </div>

            {detail.apiKey && (
              <div className="history-actions">
                <button
                  className="primary-button"
                  disabled={loading}
                  onClick={() => {
                    if (detail.apiKey) {
                      openHistory(detail.apiKey, 'Request activity')
                    }
                  }}
                >
                  View requests
                </button>
                <button
                  className="close-button"
                  disabled={loading}
                  onClick={() => {
                    if (detail.apiKey) {
                      openHistory(detail.apiKey, 'Security events')
                    }
                  }}
                >
                  View security events
                </button>
              </div>
            )}

            <dl>
              {detail.fields.map(([label, value]) => (
                <div className="detail-field" key={label}>
                  <dt>{label}</dt><dd>{value}</dd>
                </div>
              ))}
            </dl>

            {detail.apiKey && (
              <RevokeKeyButton
                key={detail.apiKey.id}
                apiKey={detail.apiKey}
                onRevoked={() => {
                  void load()
                }}
              />
            )}
          </section>
        </div>
      )}
    </div>
  )
}