import { useEffect, useRef, useState } from 'react'

type AccessData = {
  business_owner_id: string
  api_access_enabled: boolean
  csrf_token: string
  rate_limit_requests_per_minute: number | null
  pending_rate_limit_requests_per_minute: number | null
  rate_limit_effective_at: string | null
  default_rate_limit_requests_per_minute: number
  daily_creation_quota: number | null
  default_daily_creation_quota: number
}

type AccessUpdate =
  | { api_access_enabled: boolean }
  | { rate_limit_requests_per_minute: number | null }
  | { daily_creation_quota: number | null }

function configuredRateLimit(data: AccessData) {
  return data.rate_limit_effective_at
    ? data.pending_rate_limit_requests_per_minute
    : data.rate_limit_requests_per_minute
}

type Props = {
  businessId: string
  disabled: boolean
  onChanged: () => void
}

async function readAccess(
  url: string,
  signal?: AbortSignal,
): Promise<AccessData> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
  })

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Please sign in to Django admin.')
    }
    if (response.status === 403) {
      throw new Error('An active superuser account is required.')
    }
    if (response.status === 404) {
      throw new Error('No API keys were found for this business.')
    }
    throw new Error(`Unable to load access settings (${response.status}).`)
  }

  const data = await response.json() as AccessData

  if (
    typeof data.api_access_enabled !== 'boolean' ||
    typeof data.csrf_token !== 'string' ||
    !data.csrf_token
  ) {
    throw new Error('Unable to read the business access settings.')
  }

  return data
}

export default function BusinessApiAccessPanel({
  businessId,
  disabled,
  onChanged,
}: Props) {
  const [access, setAccess] = useState<AccessData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reason, setReason] = useState('')
  const [rateLimit, setRateLimit] = useState('')
  const [dailyQuota, setDailyQuota] = useState('')
  const mounted = useRef(false)
  const submitting = useRef(false)

  const url =
    `/dashboard-api/businesses/${encodeURIComponent(businessId)}/api-access/`

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()

    async function initialize() {
      try {
        const current = await readAccess(url, controller.signal)
        if (!controller.signal.aborted) {
          setAccess(current)
          setRateLimit(String(configuredRateLimit(current) ?? ''))
          setDailyQuota(String(current.daily_creation_quota ?? ''))
        }
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(
            failure instanceof Error
              ? failure.message
              : 'Unable to load business access.',
          )
        }
      }
    }

    void initialize()

    return () => {
      mounted.current = false
      controller.abort()
    }
  }, [url])

  function changeAccess() {
    if (!access || disabled || submitting.current) return

    const enabled = !access.api_access_enabled
    const confirmed = window.confirm(
      `${enabled ? 'Enable' : 'Disable'} API access for business:\n` +
      `${businessId}\n\n` +
      (
        enabled
          ? 'Valid keys will be able to make requests again. ' +
            'Revoked and expired keys will remain unusable.'
          : 'All test and live keys for this business will be blocked ' +
            'from making new API requests. Keys and history will be preserved.'
      ),
    )

    if (confirmed) void saveAccess({ api_access_enabled: enabled })
  }

  function changeNumericSetting(
    field: 'rate_limit_requests_per_minute' | 'daily_creation_quota',
    value: string,
  ) {
    const input = value.trim()
    const limit = input ? Number(input) : null
    if (limit !== null && (
      !/^\d+$/.test(input) ||
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > 2147483647
    )) {
      setError('Enter a positive whole number up to 2147483647, or leave it blank.')
      return
    }

    if (field === 'daily_creation_quota') {
      void saveAccess({ daily_creation_quota: limit })
    } else {
      void saveAccess({ rate_limit_requests_per_minute: limit })
    }
  }

  async function saveAccess(update: AccessUpdate) {
    if (!access || disabled || submitting.current) return

    submitting.current = true
    setBusy(true)
    setError('')

    try {
      // Refresh the session token and check for another administrator's change.
      const current = await readAccess(url)
      if (!mounted.current) return

      const field = Object.keys(update)[0] as keyof AccessData
      const settingChanged = field === 'rate_limit_requests_per_minute'
        ? configuredRateLimit(current) !== configuredRateLimit(access)
        : current[field] !== access[field]
      if (settingChanged) {
        setAccess(current)
        setRateLimit(String(configuredRateLimit(current) ?? ''))
        setDailyQuota(String(current.daily_creation_quota ?? ''))
        setError('This setting changed since the panel loaded. Review it and try again.')
        return
      }

      const response = await fetch(url, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': current.csrf_token,
        },
        body: JSON.stringify({
          ...update,
          reason: reason.trim(),
        }),
      })

      if (!response.ok) {
        throw new Error(
          `Update was not confirmed (${response.status}). ` +
          'Refresh data to check the current status before trying again.',
        )
      }

      if (!mounted.current) return

      const updated: AccessData = {
        ...await response.json(),
        csrf_token: current.csrf_token,
      }
      if (!mounted.current) return

      setAccess(updated)
      setRateLimit(String(configuredRateLimit(updated) ?? ''))
      setDailyQuota(String(updated.daily_creation_quota ?? ''))
      if ('api_access_enabled' in update) {
        window.alert(
          `Business API access ${update.api_access_enabled ? 'enabled' : 'disabled'}.`,
        )
      }
      onChanged()
    } catch (failure) {
      if (mounted.current) {
        // A lost response does not prove whether the update committed.
        setAccess(null)
        setError(
          failure instanceof Error
            ? failure.message
            : 'Update was not confirmed. Refresh data to check the status.',
        )
      }
    } finally {
      submitting.current = false
      if (mounted.current) setBusy(false)
    }
  }

  return (
    <section className="business-access" aria-labelledby="business-access-title">
      <div className="business-access-heading">
        <h2 id="business-access-title">Business API access</h2>
        {access && (
          <span className={`badge ${access.api_access_enabled ? 'good' : 'warning'}`}>
            {access.api_access_enabled ? 'Enabled' : 'Disabled'}
          </span>
        )}
      </div>

      <p className="identifier">{businessId}</p>
      <p className="muted">
        Applies to all test and live keys belonging to this business.
        Individual key permissions, expiration, and revocation still apply.
      </p>

      {!access && !error && <p role="status">Loading access settings…</p>}
      {error && <p className="error-banner" role="alert">{error}</p>}

      {access && (
        <>
          <div className="business-settings-access-actions">
            <label htmlFor="business-access-reason">Reason (optional)</label>
            <textarea
              id="business-access-reason"
              value={reason}
              onChange={event => setReason(event.target.value)}
              maxLength={500}
              rows={2}
              placeholder="Explain why business access is changing"
              disabled={busy || disabled}
            />

            <button
              type="button"
              className={
                access.api_access_enabled ? 'danger-button' : 'primary-button'
              }
              disabled={busy || disabled}
              onClick={changeAccess}
            >
              {busy
                ? 'Saving…'
                : access.api_access_enabled
                  ? 'Disable business API access'
                  : 'Enable business API access'}
            </button>
          </div>

          <div className="business-settings-grid">
            <div className="business-settings-card">
              <h3>Business rate limit</h3>
              <p className="muted">
                Current limit: {access.rate_limit_requests_per_minute ??
                  access.default_rate_limit_requests_per_minute} requests per minute
                per key without its own override.
              </p>
              {access.rate_limit_effective_at && (
                <p role="status">
                  Scheduled: {access.pending_rate_limit_requests_per_minute ??
                    access.default_rate_limit_requests_per_minute} requests per
                  minute starting at {new Date(access.rate_limit_effective_at)
                    .toLocaleTimeString()}.
                </p>
              )}
              <label htmlFor="business-rate-limit">Requests per minute</label>
              <input
                id="business-rate-limit"
                type="text"
                inputMode="numeric"
                value={rateLimit}
                onChange={event => setRateLimit(event.target.value)}
                placeholder={String(access.default_rate_limit_requests_per_minute)}
                disabled={busy || disabled}
                aria-describedby="business-rate-limit-help"
              />
              <p id="business-rate-limit-help" className="muted">
                Leave blank to use the default. Changes start at the next minute boundary.
              </p>
              <button
                type="button"
                className="primary-button"
                disabled={busy || disabled}
                onClick={() => changeNumericSetting('rate_limit_requests_per_minute', rateLimit)}
              >
                Save rate limit
              </button>
            </div>
            <div className="business-settings-card">
              <h3>Daily creation quota</h3>
              <p className="muted">
                Current quota: {access.daily_creation_quota ??
                  access.default_daily_creation_quota} aerrands per UTC day across
                the business's API keys.
              </p>
              <label htmlFor="business-daily-quota">Aerrands per day</label>
              <input
                id="business-daily-quota"
                type="text"
                inputMode="numeric"
                value={dailyQuota}
                onChange={event => setDailyQuota(event.target.value)}
                placeholder={String(access.default_daily_creation_quota)}
                disabled={busy || disabled}
                aria-describedby="business-daily-quota-help"
              />
              <p id="business-daily-quota-help" className="muted">
                Leave blank to use the default. Usage resets at midnight UTC.
              </p>
              <button
                type="button"
                className="primary-button"
                disabled={busy || disabled}
                onClick={() => changeNumericSetting('daily_creation_quota', dailyQuota)}
              >
                Save daily quota
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}