/**
 * The single place the browser talks to the backend.
 *
 * Every network call in the app goes through here, which keeps three
 * invariants easy to audit:
 *   1. The client only ever calls our own FastAPI origin — never Groq.
 *   2. No API key or database credential exists in this bundle.
 *   3. Errors arrive as a typed ApiError with the backend message intact.
 */

import type {
  ApiErrorBody,
  DashboardResponse,
  HealthResponse,
  MetricsResponse,
  QueryResponse,
  SuggestionsResponse,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown
  readonly sql?: string

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || 'The request failed.')
    this.name = 'ApiError'
    this.status = status
    this.code = body.error || 'unknown_error'
    this.details = body.details
    this.sql = body.sql
  }

  /** A short, user-facing hint about what to do next. */
  get hint(): string | null {
    switch (this.code) {
      case 'llm_not_configured':
        return 'Set GROQ_API_KEY in the backend environment and restart the API.'
      case 'llm_auth_failed':
        return 'The server rejected the configured Groq credentials.'
      case 'llm_rate_limited':
        return 'The model provider is throttling requests — try again shortly.'
      case 'llm_timeout':
        return 'The model took too long to answer. Try a simpler question.'
      case 'sql_validation_failed':
      case 'query_execution_failed':
        return 'Try rephrasing the question, or be more specific about the metric.'
      case 'network_error':
        return 'Check that the FastAPI backend is running.'
      default:
        return null
    }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE_URL + path, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError(0, {
      error: 'network_error',
      message: 'Could not reach the API server.',
    })
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const body =
      payload && typeof payload === 'object'
        ? (payload as ApiErrorBody)
        : {
            error: 'http_error',
            message: 'The server returned ' + response.status + '.',
          }
    throw new ApiError(response.status, body)
  }

  return payload as T
}

export const api = {
  askQuestion(
    question: string,
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<QueryResponse> {
    return request<QueryResponse>('/query', {
      method: 'POST',
      body: JSON.stringify({ question, session_id: sessionId }),
      signal,
    })
  },

  getSuggestions(signal?: AbortSignal): Promise<SuggestionsResponse> {
    return request<SuggestionsResponse>('/suggestions', { signal })
  },

  getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    return request<HealthResponse>('/health', { signal })
  },

  getMetrics(signal?: AbortSignal): Promise<MetricsResponse> {
    return request<MetricsResponse>('/metrics', { signal })
  },

  getDashboard(signal?: AbortSignal): Promise<DashboardResponse> {
    return request<DashboardResponse>('/dashboard', { signal })
  },
}
