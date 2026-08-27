import { api } from '../api'
import { usePolling } from '../usePolling'
import { formatPaise, humanizeKey, isPaiseField } from '../utils'
import OfflineBanner from './OfflineBanner'

function RuleValue({ value, keyName }) {
  if (isPaiseField(keyName)) return <span>{formatPaise(value)}</span>
  if (value === null || value === undefined) return <span className="muted">—</span>
  if (typeof value === 'boolean') return <span>{value ? 'Yes' : 'No'}</span>
  if (Array.isArray(value)) {
    return (
      <ul className="rule-array">
        {value.map((v, i) => (
          <li key={i}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') {
    return (
      <dl className="dl-grid nested">
        {Object.entries(value).map(([k, v]) => (
          <div className="dl-row" key={k}>
            <dt>{humanizeKey(k)}</dt>
            <dd>
              <RuleValue value={v} keyName={k} />
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  return <span>{String(value)}</span>
}

export default function Policy() {
  const { data, error, loading } = usePolling(() => api.getActivePolicy(), [], 3000)
  const policy = data?.policy

  return (
    <div className="view">
      <div className="view-header">
        <h1>Policy</h1>
        <p className="view-subtitle">The active merchant policy governing agent purchases.</p>
      </div>

      <OfflineBanner show={!!error} />

      {loading && !data ? (
        <div className="empty-state">Loading policy…</div>
      ) : !policy ? (
        <div className="card empty-state">No active policy configured.</div>
      ) : (
        <>
          {policy.source_text && (
            <div className="card">
              <h3>Source</h3>
              <blockquote className="quote-block">{policy.source_text}</blockquote>
              {policy.confirmed_by && (
                <div className="muted small-text">Confirmed by {policy.confirmed_by}</div>
              )}
            </div>
          )}

          {policy.rules && (
            <div className="card">
              <h3>Rules</h3>
              <dl className="dl-grid">
                {Object.entries(policy.rules).map(([k, v]) => (
                  <div className="dl-row" key={k}>
                    <dt>{humanizeKey(k)}</dt>
                    <dd>
                      <RuleValue value={v} keyName={k} />
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </>
      )}
    </div>
  )
}
