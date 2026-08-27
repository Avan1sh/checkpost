import { api } from '../api'
import { usePolling } from '../usePolling'
import { formatTime } from '../utils'
import OfflineBanner from './OfflineBanner'

const ACTOR_CLASSES = ['actor-a', 'actor-b', 'actor-c', 'actor-d', 'actor-e']

function actorClass(actor) {
  const s = String(actor || '')
  let hash = 0
  for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0
  return ACTOR_CLASSES[hash % ACTOR_CLASSES.length]
}

export default function AuditLog() {
  const { data, error, loading } = usePolling(() => api.getAudit(), [], 3000)
  const events = (data?.events || [])
    .slice()
    .sort((a, b) => new Date(b.at) - new Date(a.at))

  return (
    <div className="view">
      <div className="view-header">
        <h1>Audit Log</h1>
        <p className="view-subtitle">Live tail of every recorded gateway event.</p>
      </div>

      <OfflineBanner show={!!error} />

      <div className="card">
        {loading && !data ? (
          <div className="empty-state">Loading audit log…</div>
        ) : events.length === 0 ? (
          <div className="empty-state">No audit events yet.</div>
        ) : (
          <div className="live-tail">
            {events.map((e) => (
              <div className="live-tail-row" key={e.id}>
                <span className="muted live-tail-time">{formatTime(e.at)}</span>
                <span className={`live-tail-actor ${actorClass(e.actor)}`}>{e.actor}</span>
                <span className="mono live-tail-action">{e.action}</span>
                {e.proposal_id && <span className="mono muted live-tail-proposal">{e.proposal_id}</span>}
                {e.detail && (
                  <span className="live-tail-detail muted">
                    {typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail)}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
