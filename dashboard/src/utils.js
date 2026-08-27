export function formatPaise(paise) {
  if (paise === null || paise === undefined || Number.isNaN(Number(paise))) return '—'
  const rupees = Number(paise) / 100
  return `₹${rupees.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const SUCCESS_STATES = new Set(['paid', 'fulfilled'])
const DANGER_STATES = new Set(['blocked', 'rejected', 'denied', 'failed'])
const WARNING_STATES = new Set(['pending_approval', 'uncertain', 'reconciling'])

export function stateTone(state) {
  const s = String(state || '').toLowerCase()
  if (SUCCESS_STATES.has(s)) return 'success'
  if (DANGER_STATES.has(s)) return 'danger'
  if (WARNING_STATES.has(s)) return 'warning'
  return 'neutral'
}

export function humanizeKey(key) {
  return String(key)
    .replace(/_paise$/, '')
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase())
}

export function isPaiseField(key) {
  return /_paise$/.test(key)
}
