import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../api/client'
import type { QueryResponse } from '../api/types'
import { loadSessionId, resetSessionId } from '../lib/session'

export type ChatMessage =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; response: QueryResponse }
  | { id: string; role: 'error'; text: string; hint: string | null; code: string }

let counter = 0
const nextId = () => 'm' + ++counter

interface UseAssistantOptions {
  /** Called after every completed request so sibling widgets can refresh. */
  onSettled?: () => void
}

/**
 * Owns the conversation state and the request lifecycle.
 *
 * A single in-flight request is tracked with an AbortController so the user can
 * cancel a slow query, and so unmounting never sets state on a dead component.
 */
export function useAssistant({ onSettled }: UseAssistantOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(loadSessionId)
  const inFlight = useRef<AbortController | null>(null)

  useEffect(() => () => inFlight.current?.abort(), [])

  const ask = useCallback(
    async (rawQuestion: string) => {
      const question = rawQuestion.trim()
      if (!question || isLoading) return

      inFlight.current?.abort()
      const controller = new AbortController()
      inFlight.current = controller

      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: 'user', text: question },
      ])
      setLoading(true)

      try {
        const response = await api.askQuestion(question, sessionId, controller.signal)
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: 'assistant', response },
        ])
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError(0, {
                error: 'unknown_error',
                message: 'Something went wrong while answering that question.',
              })
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: 'error',
            text: apiError.message,
            hint: apiError.hint,
            code: apiError.code,
          },
        ])
      } finally {
        if (inFlight.current === controller) {
          inFlight.current = null
          setLoading(false)
        }
        onSettled?.()
      }
    },
    [isLoading, onSettled, sessionId],
  )

  const cancel = useCallback(() => {
    inFlight.current?.abort()
    inFlight.current = null
    setLoading(false)
  }, [])

  const clear = useCallback(() => {
    inFlight.current?.abort()
    inFlight.current = null
    setLoading(false)
    setMessages([])
    setSessionId(resetSessionId())
  }, [])

  return { messages, isLoading, sessionId, ask, cancel, clear }
}
