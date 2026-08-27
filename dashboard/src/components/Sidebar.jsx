const NAV_ITEMS = [
  { key: 'traffic', label: 'Agent Traffic', icon: '⇄' },
  { key: 'approvals', label: 'Approvals', icon: '✓' },
  { key: 'policy', label: 'Policy', icon: '§' },
  { key: 'audit', label: 'Audit Log', icon: '≡' },
]

export default function Sidebar({ view, onNavigate, approvalsCount }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">CP</div>
        <div>
          <div className="brand-name">Checkpost</div>
          <div className="brand-sub">Sehat Pharmacy</div>
        </div>
      </div>
      <nav className="nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            className={`nav-item ${view === item.key ? 'active' : ''}`}
            onClick={() => onNavigate(item.key)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
            {item.key === 'approvals' && approvalsCount > 0 && (
              <span className="nav-count">{approvalsCount}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="live-dot" />
        Live · polling 3s
      </div>
    </aside>
  )
}
