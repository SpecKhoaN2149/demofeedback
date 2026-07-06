import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import Card from './Card'

// Feature: spectrum-ui-redesign, Property 4: Card bordered mode removes shadow
//
// For any Card rendered with bordered={true} (and any combination of the
// interactive flag / children text), the rendered container SHALL carry the
// `bordered` CSS Module class token. That token is defined in Card.module.css
// with `border: 1px solid var(--spectrum-color-neutral-200)` and
// `box-shadow: none`, so its presence encodes both the border and the removal
// of the shadow.
//
// jsdom does not resolve CSS Module stylesheet values into computed styles, so
// we assert on the presence of the `bordered` class token rather than the
// computed border/box-shadow values.
//
// Validates: Requirements 5.4

describe('Card bordered mode (property-based)', () => {
  it('always applies the bordered class token when bordered=true', () => {
    fc.assert(
      fc.property(
        // Random children text (may be empty).
        fc.string(),
        // Random interactive flag to exercise class-composition combinations.
        fc.boolean(),
        (childrenText, interactive) => {
          const { container, unmount } = render(
            <Card bordered interactive={interactive}>
              {childrenText}
            </Card>
          )

          const el = container.firstElementChild as HTMLElement

          // CSS Modules hash class names, so assert on the substring token.
          expect(el.className).toContain('bordered')

          unmount()
        }
      ),
      { numRuns: 200 }
    )
  })

  it('never applies the bordered class token when bordered=false', () => {
    fc.assert(
      fc.property(fc.string(), fc.boolean(), (childrenText, interactive) => {
        const { container, unmount } = render(
          <Card bordered={false} interactive={interactive}>
            {childrenText}
          </Card>
        )

        const el = container.firstElementChild as HTMLElement

        expect(el.className).not.toContain('bordered')

        unmount()
      }),
      { numRuns: 200 }
    )
  })
})
