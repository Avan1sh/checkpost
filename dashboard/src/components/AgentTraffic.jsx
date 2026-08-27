import { api } from '../api'
import { usePolling } from '../usePolling'
import { formatPaise, formatTime } from '../utils'
import Badge from './Badge'
import OfflineBanner from './OfflineBanner'

export default function AgentTraffic({ onSelectProposal }) {
  const { data, error, loading } = usePolling(() => api.getProposals(), [], 3000)

  const proposals = (data?.proposals || [])
    .slice()
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

  return (
    <div className="view">
      <div className="view-header">
        <h1>Agent Traffic</h1>
        <p className="view-subtitle">Live proposals coming in from AI buyer agents.</p>
      </div>

      <OfflineBanner show={!!error} />

      <div className="card">
        {loading && !data ? (
          <div className="empty-state">Loading proposals…</div>
        ) : proposals.length === 0 ? (
          <div className="empty-state">No proposals yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Proposal</th>
                <th>State</th>
                <th>Agent</th>
                <th>Intent</th>
                <th>Total</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {proposals.map((p) => (
                <tr
                  key={p.proposal_id}
                  className="table-row-clickable"
                  onClick={() => onSelectProposal(p.proposal_id)}
                >
                  <td className="mono">{p.proposal_id}</td>
                  <td>
                    <Badge state={p.state} />
                  </td>
                  <td>{p.agent || '—'}</td>
                  <td className="truncate">{p.intent_text || '—'}</td>
                  <td className="amount">{formatPaise(p.total_paise)}</td>
                  <td className="muted">{formatTime(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
