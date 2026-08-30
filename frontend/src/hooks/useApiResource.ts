import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'

type Loader<T> = (signal: AbortSignal) => Promise<T>

export interface ApiResource<T> {
  data: T | null
  isLoading: boolean
  error: string | null
  reload: () => void
}

/**
 * Small fetch-on-mount helper with cancellation and a manual reload.
 *
 * The app has a handful of read-only GET endpoints (health, metrics,
 * suggestions, dashboard) that all need the same loading/error/refresh
 * behaviour; this keeps that logic in one place instead of a data-fetching
 * library the project does not otherwise need.
 */
export function useApiResource<T>(
  loader: Loader<T>,
  deps: readonly unknown[] = [],
): ApiResource<T> {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)

    loader(controller.signal)
      .then((result) => {
        if (controller.signal.aborted || !mounted.current) return
        setData(result)
        setError(null)
      })
      .catch((cause) => {
        if (controller.signal.aborted || !mounted.current) return
        setError(
          cause instanceof ApiError ? cause.message : 'Could not load this data.',
        )
      })
      .finally(() => {
        if (controller.signal.aborted || !mounted.current) return
        setLoading(false)
      })

    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return { data, isLoading, error, reload }
}
