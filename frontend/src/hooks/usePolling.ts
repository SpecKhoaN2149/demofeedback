import { useEffect, useRef, useState, useCallback } from 'react'
import { getFeedbackStatus, FeedbackStatus } from '../api/client'

/** Polling configuration constants */
const INITIAL_INTERVAL_MS = 5000
const MIN_INTERVAL_MS = 3000
const MAX_INTERVAL_MS = 10000
const BACKOFF_BASE_MS = 5000
const BACKOFF_MAX_MS = 60000
const MAX_CONSECUTIVE_FAILURES = 10

/** Enrichment states that represent a terminal (no longer "in progress") result. */
const TERMINAL_ENRICHMENT_STATES: ReadonlyArray<FeedbackStatus['enrichment_status']> = [
  'completed',
  'failed',
  'timeout',
]

export interface UsePollingResult {
  status: FeedbackStatus | null
  error: Error | null
  isComplete: boolean
  connectionLost: boolean
  retry: () => void
}

/**
 * Determines whether a feedback status represents a terminal enrichment state.
 * Polling stops once enrichment has reached completed/failed/timeout. Exported
 * for testing and reuse by the render layer.
 */
export function isTerminalStatus(status: FeedbackStatus): boolean {
  return TERMINAL_ENRICHMENT_STATES.includes(status.enrichment_status)
}

/**
 * Computes the backoff interval for a given number of consecutive failures.
 * Formula: min(5000 × 2^(n-1), 60000) ms
 * Exported for testing.
 */
export function computeBackoff(failureCount: number): number {
  if (failureCount <= 0) return INITIAL_INTERVAL_MS
  const backoff = BACKOFF_BASE_MS * Math.pow(2, failureCount - 1)
  return Math.min(backoff, BACKOFF_MAX_MS)
}

/**
 * Clamps a polling interval to the min/max range.
 * Used for the normal (non-backoff) polling interval.
 */
function clampInterval(interval: number): number {
  return Math.max(MIN_INTERVAL_MS, Math.min(MAX_INTERVAL_MS, interval))
}

/**
 * Custom hook for polling feedback status with exponential backoff.
 *
 * - Starts polling immediately on mount
 * - Calls getFeedbackStatus(id) at each interval
 * - On success: resets failure count, stores status
 * - On failure: increments failure count, applies exponential backoff
 * - Stops polling once enrichment reaches a terminal state (completed/failed/
 *   timeout) or after 10 consecutive failures
 * - Exposes a manual retry() function to restart after connection lost
 * - Cleans up interval on unmount
 *
 * Requirements: 8.1, 8.2, 9.1, 9.2, 9.4
 */
export function usePolling(feedbackId: string | null): UsePollingResult {
  const [status, setStatus] = useState<FeedbackStatus | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isComplete, setIsComplete] = useState(false)
  const [connectionLost, setConnectionLost] = useState(false)

  const failureCountRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)
  const pollRef = useRef<() => void>(() => {})

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const scheduleNext = useCallback((delayMs: number) => {
    clearTimer()
    timerRef.current = setTimeout(() => {
      pollRef.current()
    }, delayMs)
  }, [clearTimer])

  const poll = useCallback(async () => {
    if (!feedbackId || !mountedRef.current) return

    try {
      const response = await getFeedbackStatus(feedbackId)

      if (!mountedRef.current) return

      // Success: reset failure count and store status
      failureCountRef.current = 0
      setStatus(response)
      setError(null)
      setConnectionLost(false)

      // Stop polling once enrichment has reached a terminal state
      if (isTerminalStatus(response)) {
        setIsComplete(true)
        clearTimer()
        return
      }

      // Schedule next poll at the clamped initial interval
      scheduleNext(clampInterval(INITIAL_INTERVAL_MS))
    } catch (err) {
      if (!mountedRef.current) return

      // Failure: increment failure count, apply backoff
      failureCountRef.current += 1
      const currentFailures = failureCountRef.current
      setError(err instanceof Error ? err : new Error(String(err)))

      // Stop after MAX_CONSECUTIVE_FAILURES
      if (currentFailures >= MAX_CONSECUTIVE_FAILURES) {
        setConnectionLost(true)
        clearTimer()
        return
      }

      // Schedule with exponential backoff
      const backoffInterval = computeBackoff(currentFailures)
      scheduleNext(backoffInterval)
    }
  }, [feedbackId, clearTimer, scheduleNext])

  // Keep pollRef in sync with the latest poll function
  pollRef.current = poll

  const startPolling = useCallback(() => {
    if (!feedbackId) return

    // Reset state for a fresh start
    failureCountRef.current = 0
    setConnectionLost(false)
    setIsComplete(false)
    setError(null)

    // Poll immediately
    pollRef.current()
  }, [feedbackId])

  /** Manual retry function to restart polling after connection lost */
  const retry = useCallback(() => {
    startPolling()
  }, [startPolling])

  // Start polling on mount / when feedbackId changes
  useEffect(() => {
    mountedRef.current = true

    if (feedbackId) {
      startPolling()
    }

    return () => {
      mountedRef.current = false
      clearTimer()
    }
  }, [feedbackId, startPolling, clearTimer])

  return {
    status,
    error,
    isComplete,
    connectionLost,
    retry,
  }
}
