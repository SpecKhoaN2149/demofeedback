import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import ProgressBar, { type ProgressBarProps } from './ProgressBar'

// Feature: spectrum-ui-redesign, Property 5: ProgressBar size maps to height
//
// For any valid ProgressBar size (small, default, large), the rendered track
// element SHALL have a height matching the specification (small: 4px,
// default: 8px, large: 12px). Those heights are defined in
// ProgressBar.module.css keyed off the size CSS Module class tokens
// (`.small { height: 4px }`, `.default { height: 8px }`, `.large { height: 12px }`).
//
// jsdom does not resolve CSS Module stylesheet values into computed px heights,
// so we assert that the track carries the expected size class identifier that
// the component applies for each size — the token that encodes the height.
//
// Validates: Requirements 6.5

type Size = NonNullable<ProgressBarProps['size']>

// Map each size to the class token the component applies, which the stylesheet
// binds to the corresponding track height.
const sizeToClassToken: Record<Size, string> = {
  small: 'small', // height: 4px
  default: 'default', // height: 8px
  large: 'large', // height: 12px
}

describe('ProgressBar size maps to height (property-based)', () => {
  it('applies the size class token corresponding to the requested size', () => {
    fc.assert(
      fc.property(
        // Random valid size variant.
        fc.constantFrom<Size>('small', 'default', 'large'),
        // Random value across the [0, 100] progress range.
        fc.integer({ min: 0, max: 100 }),
        (size, value) => {
          const { getByRole, unmount } = render(
            <ProgressBar value={value} size={size} />
          )

          const track = getByRole('progressbar')

          // CSS Modules hash class names, so assert on the substring token that
          // the stylesheet maps to the expected height.
          expect(track.className).toContain(sizeToClassToken[size])

          // Guard against cross-contamination: only the requested size token
          // should be present among the size variants.
          const otherSizes = (['small', 'default', 'large'] as Size[]).filter(
            (s) => s !== size
          )
          for (const other of otherSizes) {
            // 'default' is a substring concern only against itself; the tokens
            // small/default/large are mutually non-overlapping, so this holds.
            expect(track.className).not.toContain(sizeToClassToken[other])
          }

          unmount()
        }
      ),
      { numRuns: 200 }
    )
  })
})
