import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePolling, computeBackoff } from './usePolling'
import * as client from '../api/client'

// Mock the API client
vi.mock('../api/client', () => ({
  getSubmissionStatus: vi.fn(),
}))

const mockGetSubmissionStatus = vi.mocked(client.getSubmissionStatus)

/**
 * Advances fake timers by `ms` and flushes any pending promises/microtasks
 * created by the async poll (getSubmissionStatus). Using the *async* timer
 * API is essential here: the hook awaits a fetch inside each poll, so a
 * synchronous `advanceTimersByTime` would fire the timer callback but leave
 * the awaited promise (and the resulting React state update) unresolved.
 * Wrapping in `act` flushes the React re-render deterministically.
 */
async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not poll when submissionId is null', () => {
    renderHook(() => usePolling(null))
    expect(mockGetSubmissionStatus).not.toHaveBeenCalled()
  })

  it('polls immediately on mount with a valid submissionId', async () => {
    const mockResponse: client.StatusResponse = {
      submission_id: 'test-id',
      progress_state: 50,
      sentiment: 'negative',
      message: 'Spectrum is working on this.',
      enrichment_status: 'pending',
    }
    mockGetSubmissionStatus.mockResolvedValueOnce(mockResponse)

    const { result } = renderHook(() => usePolling('test-id'))

    // Flush the immediate mount poll and its resulting state update
    await advance()

    expect(mockGetSubmissionStatus).toHaveBeenCalledWith('test-id')
    expect(result.current.status).toEqual(mockResponse)
    expect(result.current.isComplete).toBe(false)
    expect(result.current.connectionLost).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('stops polling when progress_state reaches 100', async () => {
    const mockResponse: client.StatusResponse = {
      submission_id: 'test-id',
      progress_state: 100,
      sentiment: 'negative',
      message: 'Resolved!',
      enrichment_status: 'completed',
    }
    mockGetSubmissionStatus.mockResolvedValueOnce(mockResponse)

    const { result } = renderHook(() => usePolling('test-id'))

    await advance()

    expect(result.current.isComplete).toBe(true)
    expect(result.current.status?.progress_state).toBe(100)

    // Advance time — no more polls should fire
    mockGetSubmissionStatus.mockClear()
    await advance(15000)
    expect(mockGetSubmissionStatus).not.toHaveBeenCalled()
  })

  it('applies exponential backoff on failure', async () => {
    mockGetSubmissionStatus.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => usePolling('test-id'))

    // First call happens immediately
    await advance()
    expect(mockGetSubmissionStatus).toHaveBeenCalledTimes(1)
    expect(result.current.error).toBeTruthy()

    // First failure → backoff = computeBackoff(1) = 5s
    mockGetSubmissionStatus.mockClear()
    await advance(computeBackoff(1))
    expect(mockGetSubmissionStatus).toHaveBeenCalledTimes(1)
  })

  it('stops polling after 10 consecutive failures and sets connectionLost', async () => {
    mockGetSubmissionStatus.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => usePolling('test-id'))

    // Poll #1 fires immediately on mount
    await advance()
    expect(mockGetSubmissionStatus).toHaveBeenCalledTimes(1)

    // Drive polls #2..#10, each after its scheduled backoff interval
    for (let n = 1; n <= 9; n++) {
      await advance(computeBackoff(n))
    }

    expect(mockGetSubmissionStatus).toHaveBeenCalledTimes(10)
    expect(result.current.connectionLost).toBe(true)

    // No more polls after connection lost
    mockGetSubmissionStatus.mockClear()
    await advance(120000)
    expect(mockGetSubmissionStatus).not.toHaveBeenCalled()
  })

  it('resets failure count on successful poll', async () => {
    // First call fails
    mockGetSubmissionStatus.mockRejectedValueOnce(new Error('fail'))

    const { result } = renderHook(() => usePolling('test-id'))

    await advance()
    expect(result.current.error).toBeTruthy()

    // After backoff, next call succeeds
    const mockResponse: client.StatusResponse = {
      submission_id: 'test-id',
      progress_state: 50,
      sentiment: 'negative',
      message: 'Spectrum is working on this.',
      enrichment_status: 'pending',
    }
    mockGetSubmissionStatus.mockResolvedValueOnce(mockResponse)

    await advance(computeBackoff(1))

    expect(result.current.status).toEqual(mockResponse)
    expect(result.current.error).toBeNull()
  })

  it('retry() restarts polling after connectionLost', async () => {
    mockGetSubmissionStatus.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => usePolling('test-id'))

    // Burn through 10 failures (poll #1 immediate, #2..#10 via backoff)
    await advance()
    for (let n = 1; n <= 9; n++) {
      await advance(computeBackoff(n))
    }

    expect(result.current.connectionLost).toBe(true)

    // Now retry with a success
    const mockResponse: client.StatusResponse = {
      submission_id: 'test-id',
      progress_state: 75,
      sentiment: 'negative',
      message: 'Almost there — resolution in progress.',
      enrichment_status: 'completed',
    }
    mockGetSubmissionStatus.mockReset()
    mockGetSubmissionStatus.mockResolvedValueOnce(mockResponse)

    await act(async () => {
      result.current.retry()
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(result.current.connectionLost).toBe(false)
    expect(result.current.status).toEqual(mockResponse)
  })

  it('cleans up on unmount', async () => {
    const mockResponse: client.StatusResponse = {
      submission_id: 'test-id',
      progress_state: 50,
      sentiment: 'negative',
      message: 'Working...',
      enrichment_status: 'pending',
    }
    mockGetSubmissionStatus.mockResolvedValue(mockResponse)

    const { unmount } = renderHook(() => usePolling('test-id'))

    await advance()
    expect(mockGetSubmissionStatus).toHaveBeenCalledTimes(1)

    unmount()

    mockGetSubmissionStatus.mockClear()
    await advance(10000)
    expect(mockGetSubmissionStatus).not.toHaveBeenCalled()
  })
})

describe('computeBackoff', () => {
  it('returns initial interval for 0 failures', () => {
    expect(computeBackoff(0)).toBe(5000)
  })

  it('computes min(5000 × 2^(n-1), 60000) for failure counts 1-10', () => {
    // n=1: 5000 × 1 = 5000
    expect(computeBackoff(1)).toBe(5000)
    // n=2: 5000 × 2 = 10000
    expect(computeBackoff(2)).toBe(10000)
    // n=3: 5000 × 4 = 20000
    expect(computeBackoff(3)).toBe(20000)
    // n=4: 5000 × 8 = 40000
    expect(computeBackoff(4)).toBe(40000)
    // n=5: 5000 × 16 = 80000 → clamped to 60000
    expect(computeBackoff(5)).toBe(60000)
    // n=6-10: all clamped to 60000
    expect(computeBackoff(6)).toBe(60000)
    expect(computeBackoff(7)).toBe(60000)
    expect(computeBackoff(8)).toBe(60000)
    expect(computeBackoff(9)).toBe(60000)
    expect(computeBackoff(10)).toBe(60000)
  })
})
