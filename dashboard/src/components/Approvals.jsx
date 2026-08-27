import { useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'
import { formatPaise, formatTime } from '../utils'
import OfflineBanner from './OfflineBanner'

function ApprovalCard({ approval, onDecided }) {
  const [reviewer, setReviewer] = useState('Dr. Nair')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState(null)

  async function decide(approve) {
    setSubmitting(true)
    setErr(null)
    try {
      const res = await api.decideApproval(approval.approval_id, { approve, reviewer, note })
      setResult({ approve, ...res })
      onDecided?.()
    } catch (e) {
      setErr(e.message || 'failed to submit decision')
    } finally {
      setSubmitting(false)
    }
  }

  const reasons = Array.isArray(approval.reason) ? approval.reason : [approval.reason].filter(Boolean)

  return (
    <div className="card approval-card">
      <div className="approval-card-head">
        <span className="mono">{approval.proposal_id}</span>
        <span className="amount">{formatPaise(approval.total_paise)}</span>
      </div>
      <p className="intent-text">{approval.intent_text}</p>
      {reasons.length > 0 && (
        <ul className="reason-list">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      <div className="muted small-text">{formatTime(approval.created_at)}</div>

      {result ? (
        <div className={`approval-result ${result.approve ? 'tone-success' : 'tone-danger'}`}>
          {result.approve ? 'Approved' : 'Denied'}
          {result.payment_link_url && (
            <div className="approval-result-link">
              Payment link:{' '}
              <a className="link" href={result.payment_link_url} target="_blank" rel="noreferrer">
                {result.payment_link_url}
              </a>
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="approval-form-row">
            <label className="field-label">
              Reviewer
              <input
                className="text-input"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                disabled={submitting}
              />
            </label>
            <label className="field-label">
              Note (optional)
              <input
                className="text-input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={submitting}
                placeholder="Reason for decision…"
              />
            </label>
          </div>
          {err && <div className="inline-error">{err}</div>}
          <div className="approval-actions">
            <button className="btn btn-success" disabled={submitting} onClick={() => decide(true)}>
              Approve
            </button>
            <button className="btn btn-danger" disabled={submitting} onClick={() => decide(false)}>
              Deny
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export default function Approvals() {
  const { data, error, loading } = usePolling(() => api.getApprovals(), [], 3000)
  const approvals = data?.approvals || []

  return (
    <div className="view">
      <div className="view-header">
        <h1>Approvals</h1>
        <p className="view-subtitle">Proposals waiting on human sign-off.</p>
      </div>

      <OfflineBanner show={!!error} />

      {loading && !data ? (
        <div className="empty-state">Loading approvals…</div>
      ) : approvals.length === 0 ? (
        <div className="card empty-state">No pending approvals.</div>
      ) : (
        <div className="approval-grid">
          {approvals.map((a) => (
            <ApprovalCard key={a.approval_id} approval={a} />
          ))}
        </div>
      )}
    </div>
  )
}
