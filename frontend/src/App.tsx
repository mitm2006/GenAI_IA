import { useCallback, useEffect, useState } from 'react'

import { api } from './api/client'
import type {
  DashboardResponse,
  HealthResponse,
  MetricsResponse,
  SuggestionsResponse,
} from './api/types'
import AssistantView from './components/AssistantView'
import DashboardView from './components/DashboardView'
import Sidebar from './components/Sidebar'
import { MenuIcon } from './components/Icons'
import { useApiResource } from './hooks/useApiResource'
import { useAssistant } from './hooks/useAssistant'

export type View = 'assistant' | 'dashboard'

const VIEW_TITLES: Record<View, string> = {
  assistant: 'Ask a question',
  dashboard: 'Business dashboard',
}

export default function App() {
  const [view, setView] = useState<View>('assistant')
  const [navOpen, setNavOpen] = useState(false)

  const metrics = useApiResource<MetricsResponse>((signal) => api.getMetrics(signal))
  const health = useApiResource<HealthResponse>((signal) => api.getHealth(signal))
  const suggestions = useApiResource<SuggestionsResponse>((signal) =>
    api.getSuggestions(signal),
  )
  const dashboard = useApiResource<DashboardResponse>((signal) =>
    api.getDashboard(signal),
  )

  // Depend on `reload` (stable) rather than the resource object, which is a
  // fresh literal each render and would defeat the memoisation.
  const reloadMetrics = metrics.reload
  const refreshMetrics = useCallback(() => reloadMetrics(), [reloadMetrics])
  const assistant = useAssistant({ onSettled: refreshMetrics })

  // Close the mobile drawer whenever the view changes or the viewport widens.
  useEffect(() => {
    setNavOpen(false)
  }, [view])

  useEffect(() => {
    if (!navOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen])

  const handleSuggestion = useCallback(
    (question: string) => {
      setView('assistant')
      void assistant.ask(question)
    },
    [assistant],
  )

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <Sidebar
        view={view}
        onViewChange={setView}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        health={health.data}
        healthError={health.error}
        onRefreshHealth={health.reload}
        metrics={metrics.data}
        suggestions={suggestions.data}
        suggestionsLoading={suggestions.isLoading}
        onSuggestionSelect={handleSuggestion}
        onClearConversation={assistant.clear}
        sessionId={assistant.sessionId}
      />

      {navOpen && (
        <div
          className="scrim"
          role="presentation"
          onClick={() => setNavOpen(false)}
        />
      )}

      <div className="app-main">
        <header className="topbar">
          <button
            type="button"
            className="icon-button topbar__menu"
            aria-label="Open navigation menu"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(true)}
          >
            <MenuIcon />
          </button>
          <div className="topbar__titles">
            <h1 className="topbar__title">{VIEW_TITLES[view]}</h1>
            <p className="topbar__subtitle">
              {view === 'assistant'
                ? 'Plain-English questions, validated SQL, instant charts.'
                : 'Key metrics across revenue, customers and products.'}
            </p>
          </div>
          <span className="topbar__badge" title="Inference provider and model">
            {health.data ? health.data.model : 'connecting…'}
          </span>
        </header>

        <main id="main-content" className="app-content" tabIndex={-1}>
          {view === 'assistant' ? (
            <AssistantView
              messages={assistant.messages}
              isLoading={assistant.isLoading}
              onAsk={assistant.ask}
              onCancel={assistant.cancel}
              suggestions={suggestions.data?.suggestions ?? []}
              suggestionsLoading={suggestions.isLoading}
            />
          ) : (
            <DashboardView
              data={dashboard.data}
              isLoading={dashboard.isLoading}
              error={dashboard.error}
              onReload={dashboard.reload}
            />
          )}
        </main>
      </div>
    </div>
  )
}
