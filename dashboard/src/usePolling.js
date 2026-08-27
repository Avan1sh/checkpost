import { useEffect, useRef, useState } from 'react'

/**
 * Polls an async fetcher every `interval` ms, exposing data/error/loading state.
 * Keeps the last good data on screen when a poll fails, and just flags `offline`.
 */
export function usePolling(fetcher, deps = [], interval = 3000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const savedFetcher = useRef(fetcher)
  savedFetcher.current = fetcher

  useEffect(() => {
    let cancelled = false
    let timer

    async function tick() {
      try {
        const result = await savedFetcher.current()
        if (cancelled) return
        setData(result)
        setError(null)
      } catch (err) {
        if (cancelled) return
        setError(err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    tick()
    timer = setInterval(tick, interval)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, loading }
}
