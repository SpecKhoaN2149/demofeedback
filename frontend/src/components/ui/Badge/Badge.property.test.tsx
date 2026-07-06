import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import Badge, { type BadgeProps } from './Badge'

// Feature: spectrum-ui-redesign, Property 8: Badge color maps to semantic token
//
// For any valid Badge color (success | warning | error | info | neutral) and
// any children text, the rendered Badge SHALL apply the corresponding semantic
// CSS Module class token, and distinct color values SHALL map to distinct class
// tokens (maintaining visual distinction between colors).
//
// jsdom does not resolve CSS Module stylesheet values into computed styles, so
// we assert on the presence of the color's CSS Module class token — that token
// is defined in Badge.module.css to apply the matching semantic design-token
// background/text color.
//
// Validates: Requirements 7.4

const colors: BadgeProps['color'][] = [
  'success',
  'warning',
  'error',
  'info',
  'neutral',
]

describe('Badge color mapping (property-based)', () => {
  it('applies the color-specific class token for any color and children', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...colors),
        fc.string(),
        (color, childrenText) => {
          const { container, unmount } = render(
            <Badge color={color}>{childrenText}</Badge>
          )

          const el = container.firstElementChild as HTMLElement

          // CSS Modules hash class names, so assert on the substring token.
          expect(el.className).toContain(color)

          unmount()
        }
      ),
      { numRuns: 200 }
    )
  })

  it('maps distinct colors to distinct class tokens', () => {
    fc.assert(
      fc.property(
        // Two distinct colors drawn from the palette.
        fc
          .tuple(fc.constantFrom(...colors), fc.constantFrom(...colors))
          .filter(([a, b]) => a !== b),
        fc.string(),
        ([colorA, colorB], childrenText) => {
          const first = render(<Badge color={colorA}>{childrenText}</Badge>)
          const classA = (first.container.firstElementChild as HTMLElement)
            .className
          first.unmount()

          const second = render(<Badge color={colorB}>{childrenText}</Badge>)
          const classB = (second.container.firstElementChild as HTMLElement)
            .className
          second.unmount()

          // Distinct semantic colors must produce distinct class tokens.
          expect(classA).not.toEqual(classB)
        }
      ),
      { numRuns: 200 }
    )
  })
})
