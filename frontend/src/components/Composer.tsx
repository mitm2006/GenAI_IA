import { useEffect, useRef, useState } from 'react'

import { SendIcon, StopIcon } from './Icons'

interface ComposerProps {
  onSubmit: (question: string) => void
  onCancel: () => void
  isLoading: boolean
}

const MAX_LENGTH = 500

export default function Composer({ onSubmit, onCancel, isLoading }: ComposerProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Grow the textarea with its content, up to a sensible ceiling.
  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = Math.min(node.scrollHeight, 180) + 'px'
  }, [value])

  const submit = () => {
    const question = value.trim()
    if (!question || isLoading) return
    onSubmit(question)
    setValue('')
  }

  const remaining = MAX_LENGTH - value.length

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <label className="sr-only" htmlFor="question-input">
        Ask a business question
      </label>
      <textarea
        id="question-input"
        ref={textareaRef}
        className="composer__input"
        placeholder="Ask a business question — e.g. “Top 10 products by revenue in 2025”"
        value={value}
        maxLength={MAX_LENGTH}
        rows={1}
        disabled={isLoading}
        aria-describedby="composer-help"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            submit()
          }
        }}
      />

      <div className="composer__actions">
        {isLoading ? (
          <button
            type="button"
            className="button button--danger"
            onClick={onCancel}
          >
            <StopIcon />
            <span>Stop</span>
          </button>
        ) : (
          <button
            type="submit"
            className="button button--primary"
            disabled={!value.trim()}
          >
            <span>Ask</span>
            <SendIcon />
          </button>
        )}
      </div>

      <p id="composer-help" className="composer__help">
        <span>Enter to send · Shift + Enter for a new line</span>
        <span className={remaining < 60 ? 'composer__count is-low' : 'composer__count'}>
          {remaining}
        </span>
      </p>
    </form>
  )
}
