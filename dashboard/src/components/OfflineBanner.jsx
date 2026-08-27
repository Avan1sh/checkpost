export default function OfflineBanner({ show }) {
  if (!show) return null
  return (
    <div className="offline-banner">
      <span className="offline-dot" />
      Gateway offline — retrying every 3s…
    </div>
  )
}
