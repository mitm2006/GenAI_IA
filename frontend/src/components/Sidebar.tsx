import type { HealthResponse, MetricsResponse, SuggestionsResponse } from '../api/types'
import type { View } from '../App'
import {
  ChatIcon,
  CloseIcon,
  DashboardIcon,
  RefreshIcon,
  ShieldIcon,
  SparkIcon,
  TrashIcon,
} from './Icons'

interface SidebarProps {
  view: View
  onViewChange: (view: View) => void
  open: boolean
  onClose: () => void
  health: HealthResponse | null
  healthError: string | null
  onRefreshHealth: () => void
  metrics: MetricsResponse | null
  suggestions: SuggestionsResponse | null
  suggestionsLoading: boolean
  onSuggestionSelect: (question: string) => void
  onClearConversation: () => void
  sessionId: string
}

const NAV_ITEMS: Array<{ id: View; label: string; icon: JSX.Element }> = [
  { id: 'assistant', label: 'Assistant', icon: <ChatIcon /> },
  { id: 'dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
]

export default function Sidebar({
  view,
  onViewChange,
  open,
  onClose,
  health,
  healthError,
  onRefreshHealth,
  metrics,
  suggestions,
  suggestionsLoading,
  onSuggestionSelect,
  onClearConversation,
  sessionId,
}: SidebarProps) {
  const stats = metrics?.stats
  const online = health?.llm === 'connected'
  const statusLabel = healthError
    ? 'API unreachable'
    : health
      ? online
        ? 'Model connected'
        : health.detail || 'Model unavailable'
      : 'Checking…'

  return (
    <aside
      className={'sidebar' + (open ? ' sidebar--open' : '')}
      aria-label="Application navigation and status"
    >
      <div className="sidebar__head">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            BI
          </span>
          <span className="brand__text">
            <strong>SQL Assistant</strong>
            <small>Natural language analytics</small>
          </span>
        </div>
        <button
          type="button"
          className="icon-button sidebar__close"
          onClick={onClose}
          aria-label="Close navigation menu"
        >
          <CloseIcon />
        </button>
      </div>

      <nav className="nav" aria-label="Views">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={'nav__item' + (view === item.id ? ' nav__item--active' : '')}
            aria-current={view === item.id ? 'page' : undefined}
            onClick={() => onViewChange(item.id)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <section className="sidebar__section" aria-labelledby="status-heading">
        <div className="sidebar__section-head">
          <h2 id="status-heading">Status</h2>
          <button
            type="button"
            className="icon-button icon-button--small"
            onClick={onRefreshHealth}
            aria-label="Re-check service status"
          >
            <RefreshIcon />
          </button>
        </div>
        <p className={'status' + (online ? ' status--ok' : ' status--warn')}>
          <span className="status__dot" aria-hidden="true" />
          <span>{statusLabel}</span>
        </p>
        {health && (
          <dl className="status__details">
            <div>
              <dt>Provider</dt>
              <dd>{health.provider}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd className="mono">{health.model}</dd>
            </div>
            <div>
              <dt>Schema</dt>
              <dd>{health.schema_status}</dd>
            </div>
          </dl>
        )}
        <p className="privacy-note">
          <ShieldIcon />
          <span>
            Model reasoning is suppressed server-side. Only final answers reach
            this page.
          </span>
        </p>
      </section>

      {stats && (
        <section className="sidebar__section" aria-labelledby="metrics-heading">
          <div className="sidebar__section-head">
            <h2 id="metrics-heading">Performance</h2>
          </div>
          <div className="metric-grid">
            <div className="metric">
              <span className="metric__value">{stats.total_queries}</span>
              <span className="metric__label">Queries</span>
            </div>
            <div className="metric">
              <span className="metric__value">{stats.success_rate}%</span>
              <span className="metric__label">Success</span>
            </div>
            <div className="metric">
              <span className="metric__value">
                {Math.round(stats.avg_latency_ms)}
                <small>ms</small>
              </span>
              <span className="metric__label">Avg SQL time</span>
            </div>
            <div className="metric">
              <span className="metric__value">{stats.avg_confidence}</span>
              <span className="metric__label">Avg confidence</span>
            </div>
          </div>
        </section>
      )}

      <section className="sidebar__section" aria-labelledby="suggestions-heading">
        <div className="sidebar__section-head">
          <h2 id="suggestions-heading">
            <SparkIcon /> Suggested
          </h2>
        </div>
        {suggestionsLoading ? (
          <ul className="suggestion-list" aria-hidden="true">
            {[0, 1, 2, 3].map((i) => (
              <li key={i} className="skeleton skeleton--line" />
            ))}
          </ul>
        ) : (
          <ul className="suggestion-list">
            {(suggestions?.suggestions ?? []).slice(0, 6).map((question) => (
              <li key={question}>
                <button
                  type="button"
                  className="suggestion"
                  onClick={() => onSuggestionSelect(question)}
                >
                  {question}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="sidebar__foot">
        <button type="button" className="button button--ghost" onClick={onClearConversation}>
          <TrashIcon />
          <span>Clear conversation</span>
        </button>
        <p className="session-id" title="Conversation session identifier">
          Session <code>{sessionId.slice(0, 8)}</code>
        </p>
      </div>
    </aside>
  )
}
