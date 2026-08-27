import { useState } from 'react'
import Sidebar from './components/Sidebar'
import AgentTraffic from './components/AgentTraffic'
import ProposalDetail from './components/ProposalDetail'
import Approvals from './components/Approvals'
import Policy from './components/Policy'
import AuditLog from './components/AuditLog'
import { api } from './api'
import { usePolling } from './usePolling'

export default function App() {
  const [view, setView] = useState('traffic')
  const [selectedProposalId, setSelectedProposalId] = useState(null)

  // Lightweight poll just for the sidebar approvals-count badge.
  const { data: approvalsData } = usePolling(() => api.getApprovals(), [], 3000)
  const approvalsCount = approvalsData?.approvals?.length || 0

  function navigate(next) {
    setSelectedProposalId(null)
    setView(next)
  }

  function selectProposal(id) {
    setSelectedProposalId(id)
    setView('proposal-detail')
  }

  function backToTraffic() {
    setSelectedProposalId(null)
    setView('traffic')
  }

  let content
  if (view === 'proposal-detail' && selectedProposalId) {
    content = <ProposalDetail proposalId={selectedProposalId} onBack={backToTraffic} />
  } else if (view === 'approvals') {
    content = <Approvals />
  } else if (view === 'policy') {
    content = <Policy />
  } else if (view === 'audit') {
    content = <AuditLog />
  } else {
    content = <AgentTraffic onSelectProposal={selectProposal} />
  }

  return (
    <div className="app-shell">
      <Sidebar
        view={view === 'proposal-detail' ? 'traffic' : view}
        onNavigate={navigate}
        approvalsCount={approvalsCount}
      />
      <main className="main-content">{content}</main>
    </div>
  )
}
