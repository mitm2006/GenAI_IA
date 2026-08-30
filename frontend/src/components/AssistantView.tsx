import { useEffect, useRef } from 'react'

import type { ChatMessage } from '../hooks/useAssistant'
import AnswerCard from './AnswerCard'
import Composer from './Composer'
import { AlertIcon, SparkIcon } from './Icons'

interface AssistantViewProps {
  messages: ChatMessage[]
  isLoading: boolean
  onAsk: (question: string) => void
  onCancel: () => void
  suggestions: string[]
  suggestionsLoading: boolean
}

export default function AssistantView({
  messages,
  isLoading,
  onAsk,
  onCancel,
  suggestions,
  suggestionsLoading,
}: AssistantViewProps) {
  const endRef = useRef<HTMLDivElement>(null)

  // Charts and tables mount after this effect runs and change the scroll
  // height, so scroll once now and once on the next frame batch.
  useEffect(() => {
    const scroll = () =>
      endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    scroll()
    const timer = window.setTimeout(scroll, 240)
    return () => window.clearTimeout(timer)
  }, [messages.length, isLoading])

  const isEmpty = messages.length === 0

  return (
    <div className="assistant">
      <div
        className="conversation"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation"
      >
        {isEmpty && (
          <EmptyState
            suggestions={suggestions}
            suggestionsLoading={suggestionsLoading}
            onSelect={onAsk}
          />
        )}

        {messages.map((message) => {
          if (message.role === 'user') {
            return (
              <div key={message.id} className="turn turn--user">
                <p className="bubble">{message.text}</p>
              </div>
            )
          }
          if (message.role === 'error') {
            return (
              <div key={message.id} className="turn turn--assistant">
                <div className="error-card" role="alert">
                  <AlertIcon />
                  <div>
                    <p className="error-card__title">{message.text}</p>
                    {message.hint && <p className="error-card__hint">{message.hint}</p>}
                  </div>
                </div>
              </div>
            )
          }
          return (
            <div key={message.id} className="turn turn--assistant">
              <AnswerCard response={message.response} />
            </div>
          )
        })}

        {isLoading && <ThinkingRow />}
        <div ref={endRef} />
      </div>

      <div className="composer-dock">
        <Composer onSubmit={onAsk} onCancel={onCancel} isLoading={isLoading} />
      </div>
    </div>
  )
}

function ThinkingRow() {
  return (
    <div className="turn turn--assistant">
      <div className="working" aria-live="polite">
        <span className="working__dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span>Generating SQL and running your query…</span>
      </div>
    </div>
  )
}

interface EmptyStateProps {
  suggestions: string[]
  suggestionsLoading: boolean
  onSelect: (question: string) => void
}

function EmptyState({ suggestions, suggestionsLoading, onSelect }: EmptyStateProps) {
  return (
    <section className="empty">
      <span className="empty__icon" aria-hidden="true">
        <SparkIcon />
      </span>
      <h2 className="empty__title">Ask anything about your business data</h2>
      <p className="empty__body">
        Questions are translated into validated, read-only SQL, executed against
        the analytics warehouse, and returned with a chart and a plain-English
        summary.
      </p>

      {suggestionsLoading ? (
        <div className="chip-row" aria-hidden="true">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="skeleton skeleton--chip" />
          ))}
        </div>
      ) : (
        suggestions.length > 0 && (
          <div className="chip-row">
            {suggestions.slice(0, 6).map((question) => (
              <button
                key={question}
                type="button"
                className="chip"
                onClick={() => onSelect(question)}
              >
                {question}
              </button>
            ))}
          </div>
        )
      )}
    </section>
  )
}
