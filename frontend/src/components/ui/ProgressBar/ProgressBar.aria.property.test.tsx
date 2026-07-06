// Feature: spectrum-ui-redesign, Property 6: ProgressBar ARIA attributes reflect value
import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import ProgressBar from './ProgressBar'

/**
 * Property 6: ProgressBar ARIA attributes reflect value
 *
 * For any ProgressBar with a `value` (including out-of-range values), the rendered
 * element SHALL have `role="progressbar"`, `aria-valuenow` equal to the clamped value
 * (Math.min(100, Math.max(0, value))), `aria-valuemin="0"`, and `aria-valuemax="100"`.
 *
 * Validates: Requirements 6.6
 */

describe('ProgressBar ARIA attributes (Property 6)', () => {
  it('exposes progressbar role and clamped aria-valuenow/min/max for any value', () => {
    fc.assert(
      fc.property(
        // Include out-of-range values (negative and > 100) to verify clamping.
        fc.integer({ min: -200, max: 300 }),
        (value) => {
          render(<ProgressBar value={value} />)

          try {
            const clampedValue = Math.min(100, Math.max(0, value))

            const progressbar = screen.getByRole('progressbar')

            expect(progressbar).toHaveAttribute(
              'aria-valuenow',
              String(clampedValue)
            )
            expect(progressbar).toHaveAttribute('aria-valuemin', '0')
            expect(progressbar).toHaveAttribute('aria-valuemax', '100')
          } finally {
            // Reset DOM between generated runs to avoid duplicate elements.
            cleanup()
          }
        }
      ),
      { numRuns: 200 }
    )
  })
})
