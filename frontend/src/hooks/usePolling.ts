import { useEffect, useRef, useState, useCallback } from 'react'
import { getSubmissionStatus, StatusResponse } from '../api/client'

/** Polling configuration constants */
const INITIAL_INTERVAL_MS = 5000
const MIN_INTERVAL_MS = 3000
const MAX_INTERVAL_MS = 10000
const BACKOFF_BASE_MS = 5000
const BACKOFF_MAX_MS = 60000
const MAX_CONSECUTIVE_FAILURES = 10

export interface UsePollingResult {
  status: StatusResponse | null
  error: Error | null
  isComplete: boolean
  connectionLost: boolean
  retry: () => void
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
 * Custom hook for polling submission status with exponential backoff.
 *
 * - Starts polling immediately on mount
 * - Calls getSubmissionStatus(id) at each interval
 * - On success: resets failure count, stores status
 * - On failure: increments failure count, applies exponential backoff
 * - Stops polling when progress_state === 100 or after 10 consecutive failures
 * - Exposes a manual retry() function to restart after connection lost
 * - Cleans up interval on unmount
 *
 * Requirements: 12.1, 12.3, 12.4, 12.5
 */
export function usePolling(submissionId: string | null): UsePollingResult {
  const [status, setStatus] = useState<StatusResponse | null>(null)
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
    if (!submissionId || !mountedRef.current) return

    try {
      const response = await getSubmissionStatus(submissionId)

      if (!mountedRef.current) return

      // Success: reset failure count and store status
      failureCountRef.current = 0
      setStatus(response)
      setError(null)
      setConnectionLost(false)

      // Stop polling when progress reaches 100%
      if (response.progress_state === 100) {
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
  }, [submissionId, clearTimer, scheduleNext])

  // Keep pollRef in sync with the latest poll function
  pollRef.current = poll

  const startPolling = useCallback(() => {
    if (!submissionId) return

    // Reset state for a fresh start
    failureCountRef.current = 0
    setConnectionLost(false)
    setIsComplete(false)
    setError(null)

    // Poll immediately
    pollRef.current()
  }, [submissionId])

  /** Manual retry function to restart polling after connection lost */
  const retry = useCallback(() => {
    startPolling()
  }, [startPolling])

  // Start polling on mount / when submissionId changes
  useEffect(() => {
    mountedRef.current = true

    if (submissionId) {
      startPolling()
    }

    return () => {
      mountedRef.current = false
      clearTimer()
    }
  }, [submissionId, startPolling, clearTimer])

  return {
    status,
    error,
    isComplete,
    connectionLost,
    retry,
  }
}
