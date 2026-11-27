import { useEffect, useState } from 'react'

type Trends = {
  days: number
  timezone: string
  requests: number
  failed: number
  daily: {
    date: string
    requests: number
    failed: number
  }[]
}

type Props = {
  businessId: string
  apiKeyId: string
}

export default function RequestTrends({
  businessId,
  apiKeyId,
}: Props) {
  const [days, setDays] = useState('7')
  const [trends, setTrends] = useState<Trends | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function fetchTrends() {
      try {
        const query = new URLSearchParams({ days })

        if (businessId) {
          query.set('business_owner_id', businessId)
        }

        if (apiKeyId) {
          query.set('api_key_id', apiKeyId)
        }

        const response = await fetch(
          `/dashboard-api/overview/?${query}`,
          {
            credentials: 'same-origin',
            cache: 'no-store',
            signal: controller.signal,
          },
        )

        if (!response.ok) {
          throw new Error(
            `Unable to load trends (${response.status}). Check your admin session.`,
          )
        }

        const body = await response.json() as {
          request_trends: Trends
        }

        if (!controller.signal.aborted) {
          setTrends(body.request_trends)
        }
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(
            failure instanceof Error
              ? failure.message
              : 'Unable to load trends.',
          )
        }
      }
    }

    void fetchTrends()
    return () => controller.abort()
  }, [days, businessId, apiKeyId])

  const maximum = Math.max(
    1,
    ...(trends?.daily.map(day => day.requests) ?? []),
  )

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>Request trends</h2>
          <p className="muted">
            Daily recorded requests · UTC calendar days, including today
          </p>
        </div>

        <select
          className="trend-select"
          aria-label="Request trend period"
          value={days}
          onChange={event => {
            setDays(event.target.value)
            setTrends(null)
            setError('')
          }}
        >
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
      </div>

      {error && (
        <p className="error-banner" role="alert">{error}</p>
      )}

      {!trends && !error && (
        <p className="empty" role="status">Loading request trends…</p>
      )}

      {trends && (
        <div className="trend-content">
          <div className="trend-summary">
            <span>
              <strong>{trends.requests}</strong> recorded requests
            </span>
            <span>
              <strong>{trends.failed}</strong> failed requests
            </span>
          </div>

          <p className="muted">
            Green: all requests · Red: failed requests, included in the total
          </p>

          {trends.requests === 0 && (
            <p className="muted">
              No requests recorded during this period.
            </p>
          )}

          <div className="trend-scroll">
            <div
              className="trend-chart"
              style={{
                gridTemplateColumns:
                  `repeat(${trends.daily.length}, minmax(48px, 1fr))`,
              }}
            >
              {trends.daily.map(day => (
                <div className="trend-day" key={day.date}>
                  <div className="trend-bars">
                    <div
                      className="trend-total"
                      style={{
                        height: `${day.requests / maximum * 100}%`,
                      }}
                      title={`${day.date}: ${day.requests} requests`}
                    />
                    <div
                      className="trend-failed"
                      style={{
                        height: `${day.failed / maximum * 100}%`,
                      }}
                      title={`${day.date}: ${day.failed} failed`}
                    />
                  </div>
                  <span>{day.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>

          <details className="trend-details">
            <summary>View exact daily counts</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date (UTC)</th>
                    <th>All requests</th>
                    <th>Failed requests</th>
                  </tr>
                </thead>
                <tbody>
                  {trends.daily.map(day => (
                    <tr key={day.date}>
                      <td>{day.date}</td>
                      <td>{day.requests}</td>
                      <td>{day.failed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </section>
  )
}