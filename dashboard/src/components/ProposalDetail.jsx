import { useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'
import { formatPaise, formatTime, stateTone } from '../utils'
import Badge from './Badge'
import OfflineBanner from './OfflineBanner'

function PricedCartTable({ cart }) {
  if (!cart || cart.length === 0) return <div className="empty-state">No cart items.</div>
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Item</th>
          <th>Qty</th>
          <th>Unit price</th>
          <th>Line total</th>
        </tr>
      </thead>
      <tbody>
        {cart.map((item, i) => (
          <tr key={i}>
            <td>{item.name || item.sku || item.title || `Item ${i + 1}`}</td>
            <td>{item.qty ?? item.quantity ?? '—'}</td>
            <td>{formatPaise(item.unit_paise ?? item.unit_price_paise ?? item.price_paise)}</td>
            <td className="amount">
              {formatPaise(
                item.line_paise ??
                  item.line_total_paise ??
                  (item.unit_paise && item.qty ? item.unit_paise * item.qty : undefined),
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DecisionCard({ decision }) {
  if (!decision) {
    return (
      <div className="card">
        <h3>Decision</h3>
        <div className="empty-state">No decision recorded.</div>
      </div>
    )
  }

  const verdict = decision.verdict
  const violations = verdict?.violations || []
  const escalations = verdict?.escalations || []
  const safeAlt = verdict?.safe_alternative

  return (
    <div className="card">
      <h3>Decision</h3>
      {!verdict && (
        <pre className="json-block">{JSON.stringify(decision, null, 2)}</pre>
      )}
      {verdict && (
        <>
          {violations.length === 0 && escalations.length === 0 && (
            <div className="decision-clean">No violations or escalations.</div>
          )}
          {violations.length > 0 && (
            <div className="decision-group">
              <div className="decision-group-label decision-danger">Violations</div>
              <ul className="decision-list">
                {violations.map((v, i) => (
                  <li key={i} className="decision-item decision-danger-item">
                    {v.message || JSON.stringify(v)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {escalations.length > 0 && (
            <div className="decision-group">
              <div className="decision-group-label decision-warning">Escalations</div>
              <ul className="decision-list">
                {escalations.map((v, i) => (
                  <li key={i} className="decision-item decision-warning-item">
                    {v.message || JSON.stringify(v)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {safeAlt && (
            <div className="safe-alt">
              <div className="safe-alt-label">Safe alternative</div>
              {safeAlt.note && <p className="safe-alt-note">{safeAlt.note}</p>}
              {safeAlt.cart && <PricedCartTable cart={safeAlt.cart} />}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Timeline({ transitions }) {
  if (!transitions || transitions.length === 0) {
    return <div className="empty-state">No transitions recorded yet.</div>
  }
  return (
    <div className="timeline">
      {transitions.map((t, i) => (
        <div className="timeline-row" key={i}>
          <div className="timeline-rail">
            <span className={`timeline-dot tone-${stateTone(t.to)}`} />
            {i < transitions.length - 1 && <span className="timeline-line" />}
          </div>
          <div className="timeline-content">
            <div className="timeline-transition">
              <span className="mono">{t.from || 'start'}</span>
              <span className="timeline-arrow">→</span>
              <span className="mono">{t.to}</span>
            </div>
            <div className="timeline-meta">
              <span className="timeline-actor">{t.actor || 'system'}</span>
              {t.cause && <span className="timeline-cause">{t.cause}</span>}
              <span className="timeline-time muted">{formatTime(t.at)}</span>
            </div>
            {t.evidence && (
              <pre className="json-block small">{JSON.stringify(t.evidence, null, 2)}</pre>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function AuditEvents({ events }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card">
      <button className="collapsible-toggle" onClick={() => setOpen((o) => !o)}>
        <h3 className="inline-h3">Audit events ({events?.length || 0})</h3>
        <span className="chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="audit-list">
          {(!events || events.length === 0) && <div className="empty-state">No audit events.</div>}
          {events?.map((e) => (
            <div className="audit-row" key={e.id}>
              <div className="audit-row-head">
                <span className="mono">{e.action}</span>
                <span className="muted">{e.actor}</span>
                <span className="muted">{formatTime(e.at)}</span>
              </div>
              {e.detail && <pre className="json-block small">{JSON.stringify(e.detail, null, 2)}</pre>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function LlmCalls({ calls }) {
  if (!calls || calls.length === 0) return null
  return (
    <div className="card">
      <h3>LLM calls</h3>
      <div className="llm-list">
        {calls.map((c, i) => (
          <div className="llm-row" key={i}>
            <span className="llm-role">{c.role}</span>
            <span className="mono">{c.model}</span>
            <span className="muted">{c.latency_ms != null ? `${c.latency_ms}ms` : '—'}</span>
            {c.verdict && Object.keys(c.verdict).length > 0 && (
              <span className="badge badge-neutral mono">{JSON.stringify(c.verdict)}</span>
            )}
            {c.error && <span className="badge badge-danger">{c.error}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ProposalDetail({ proposalId, onBack }) {
  const { data, error, loading } = usePolling(
    () => api.getProposal(proposalId),
    [proposalId],
    3000,
  )

  const p = data

  return (
    <div className="view">
      <button className="back-button" onClick={onBack}>
        ← Back to Agent Traffic
      </button>

      <OfflineBanner show={!!error} />

      {loading && !p ? (
        <div className="empty-state">Loading proposal…</div>
      ) : !p ? (
        <div className="empty-state">Proposal not found.</div>
      ) : (
        <>
          <div className="detail-header card">
            <div>
              <div className="detail-header-top">
                <span className="mono detail-id">{p.proposal_id}</span>
                <Badge state={p.state} />
              </div>
              <p className="intent-text">{p.intent_text}</p>
            </div>
            <div className="detail-total">
              <div className="detail-total-label">Total</div>
              <div className="detail-total-amount">{formatPaise(p.total_paise)}</div>
            </div>
          </div>

          {p.mandate && (
            <div className="card mandate-card">
              <h3>Mandate</h3>
              <div className="kv-grid">
                <div className="kv-label">Principal</div>
                <div>{p.mandate.principal || '—'}</div>
                <div className="kv-label">Purpose</div>
                <div>{p.mandate.purpose || '—'}</div>
                <div className="kv-label">Cap</div>
                <div>{formatPaise(p.mandate.max_amount_paise)}</div>
                <div className="kv-label">Mandate ID</div>
                <div className="mono">{p.mandate.id || '—'}</div>
              </div>
            </div>
          )}

          <div className="card">
            <h3>Priced cart</h3>
            <PricedCartTable cart={p.priced_cart || p.cart} />
          </div>

          <DecisionCard decision={p.decision} />

          {(p.razorpay_order_id || p.razorpay_payment_id || p.payment_link_url) && (
            <div className="card">
              <h3>Payment</h3>
              <div className="kv-grid">
                {p.razorpay_order_id && (
                  <>
                    <div className="kv-label">Order ID</div>
                    <div className="mono">{p.razorpay_order_id}</div>
                  </>
                )}
                {p.razorpay_payment_id && (
                  <>
                    <div className="kv-label">Payment ID</div>
                    <div className="mono">{p.razorpay_payment_id}</div>
                  </>
                )}
                {p.payment_link_url && (
                  <>
                    <div className="kv-label">Payment link</div>
                    <div>
                      <a className="link" href={p.payment_link_url} target="_blank" rel="noreferrer">
                        {p.payment_link_url}
                      </a>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          <div className="card">
            <h3>Timeline</h3>
            <Timeline transitions={p.transitions} />
          </div>

          <AuditEvents events={p.audit_events} />

          <LlmCalls calls={p.llm_calls} />
        </>
      )}
    </div>
  )
}
