import { stateTone } from '../utils'

export default function Badge({ state }) {
  const tone = stateTone(state)
  return <span className={`badge badge-${tone}`}>{String(state || 'unknown').replace(/_/g, ' ')}</span>
}
