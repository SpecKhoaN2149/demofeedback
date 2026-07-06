// Feature: spectrum-ui-redesign, Property 1: Button variant and size produce correct styles
import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, afterEach } from 'vitest'
import fc from 'fast-check'
import Button from './Button'

/**
 * Property 1: Button variant and size produce correct styles
 *
 * For any valid Button variant (primary, secondary, outline, ghost) and any
 * valid size (small, medium, large), rendering the Button SHALL produce an
 * element whose className includes the variant identifier and the size
 * identifier from the CSS module.
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
 */

const VARIANTS = ['primary', 'secondary', 'outline', 'ghost'] as const
const SIZES = ['small', 'medium', 'large'] as const

type Variant = (typeof VARIANTS)[number]
type Size = (typeof SIZES)[number]

const variantArb: fc.Arbitrary<Variant> = fc.constantFrom(...VARIANTS)
const sizeArb: fc.Arbitrary<Size> = fc.constantFrom(...SIZES)

describe('Property 1: Button variant and size produce correct styles', () => {
  afterEach(() => {
    cleanup()
  })

  it('renders className containing the expected variant and size class identifiers', () => {
    fc.assert(
      fc.property(variantArb, sizeArb, (variant, size) => {
        render(
          <Button variant={variant} size={size}>
            Label
          </Button>
        )

        const button = screen.getByRole('button', { name: 'Label' })

        // The base button class is always present.
        if (!button.className.includes('button')) {
          throw new Error(
            `Expected base "button" class, got "${button.className}"`
          )
        }

        // The variant identifier must be present in the rendered className.
        if (!button.className.includes(variant)) {
          throw new Error(
            `Expected variant "${variant}" in className, got "${button.className}"`
          )
        }

        // The size identifier must be present in the rendered className.
        if (!button.className.includes(size)) {
          throw new Error(
            `Expected size "${size}" in className, got "${button.className}"`
          )
        }

        cleanup()
        return true
      }),
      { numRuns: 100 }
    )
  })
})
