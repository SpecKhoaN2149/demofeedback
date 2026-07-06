/**
 * Property 8: Exponential backoff computation
 *
 * For any sequence of n consecutive polling failures (1 ≤ n ≤ 10), the retry
 * interval SHALL be min(5000 × 2^(n−1), 60000) ms. After 10 consecutive failures,
 * polling SHALL stop and an error message SHALL be displayed.
 *
 * **Validates: Requirements 6.5, 12.4, 12.5**
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { computeBackoff } from '../hooks/usePolling'

describe('Property 8: Exponential backoff computation', () => {
  it('computes min(5000 * 2^(n-1), 60000) for any n in [1, 10]', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10 }),
        (n) => {
          const expected = Math.min(5000 * Math.pow(2, n - 1), 60000)
          expect(computeBackoff(n)).toBe(expected)
        }
      ),
      { numRuns: 100 }
    )
  })

  it('returns 5000 (initial interval) when n = 0', () => {
    fc.assert(
      fc.property(
        fc.constant(0),
        (n) => {
          expect(computeBackoff(n)).toBe(5000)
        }
      ),
      { numRuns: 100 }
    )
  })

  it('result is always >= 5000 and <= 60000 for n in [1, 10]', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10 }),
        (n) => {
          const result = computeBackoff(n)
          expect(result).toBeGreaterThanOrEqual(5000)
          expect(result).toBeLessThanOrEqual(60000)
        }
      ),
      { numRuns: 100 }
    )
  })

  it('produces monotonically non-decreasing intervals for increasing failure counts', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 9 }),
        (n) => {
          const current = computeBackoff(n)
          const next = computeBackoff(n + 1)
          expect(next).toBeGreaterThanOrEqual(current)
        }
      ),
      { numRuns: 100 }
    )
  })
})
