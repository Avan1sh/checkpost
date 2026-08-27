const BASE_URL = 'http://localhost:8000'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError('network error', 0)
  }
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = body?.detail ? ` — ${JSON.stringify(body.detail)}` : ''
    } catch {
      // ignore
    }
    throw new ApiError(`request failed (${res.status})${detail}`, res.status)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  getProposals: () => request('/merchant/proposals'),
  getProposal: (id) => request(`/merchant/proposals/${id}`),
  getApprovals: () => request('/merchant/approvals'),
  decideApproval: (id, payload) =>
    request(`/merchant/approvals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getActivePolicy: () => request('/merchant/policies/active'),
  getAudit: () => request('/merchant/audit'),
}

export { ApiError }
