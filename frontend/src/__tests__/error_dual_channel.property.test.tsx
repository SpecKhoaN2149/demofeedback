import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import Input from '../components/ui/Input/Input'
import Textarea from '../components/ui/Textarea/Textarea'
import Select from '../components/ui/Select/Select'
import Alert from '../components/ui/Alert/Alert'

// Feature: spectrum-ui-redesign, Property 11: Error states use dual-channel signaling
//
// For any component that supports an error state (Input, Textarea, Select, and
// Alert with severity "error"), the error indication SHALL be conveyed through
// BOTH a color change AND a text message or icon — never relying on color alone.
//
// jsdom does not resolve CSS Module stylesheet values into computed styles, so
// the "color change" channel is asserted via the presence of the `error` CSS
// Module class token (which, in each *.module.css, applies the semantic error
// color) plus `aria-invalid="true"` for form controls. The second,
// non-color channel is asserted via a role="alert" text element (form
// controls) or an icon (svg) + text content (Alert).
//
// Validates: Requirements 13.4

// Generates a non-empty error string with at least one non-whitespace
// character, so the rendered text channel carries meaningful content.
const errorArb = fc
  .string({ minLength: 1, maxLength: 80 })
  .filter((s) => s.trim().length >= 1)

// Options used to render the Select control.
const selectOptions = [
  { value: 'a', label: 'Option A' },
  { value: 'b', label: 'Option B' },
]

describe('Property 11: Error states use dual-channel signaling', () => {
  it('Input signals error via color class + aria-invalid AND role="alert" text', () => {
    fc.assert(
      fc.property(errorArb, (error) => {
        const { container, unmount } = render(
          <Input label="Name" error={error} />
        )

        const input = container.querySelector('input') as HTMLInputElement

        // Channel 1 — color change: the error CSS Module class token is applied
        // (carries the semantic error border color) AND aria-invalid is set.
        expect(input.className).toContain('error')
        expect(input.getAttribute('aria-invalid')).toBe('true')

        // Channel 2 — text: a role="alert" element contains the error text.
        const alert = container.querySelector('[role="alert"]') as HTMLElement
        expect(alert).not.toBeNull()
        expect(alert.textContent).toBe(error)

        unmount()
      }),
      { numRuns: 150 }
    )
  })

  it('Textarea signals error via color class + aria-invalid AND role="alert" text', () => {
    fc.assert(
      fc.property(errorArb, (error) => {
        const { container, unmount } = render(
          <Textarea label="Details" error={error} />
        )

        const textarea = container.querySelector(
          'textarea'
        ) as HTMLTextAreaElement

        // Channel 1 — color change.
        expect(textarea.className).toContain('error')
        expect(textarea.getAttribute('aria-invalid')).toBe('true')

        // Channel 2 — text.
        const alert = container.querySelector('[role="alert"]') as HTMLElement
        expect(alert).not.toBeNull()
        expect(alert.textContent).toBe(error)

        unmount()
      }),
      { numRuns: 150 }
    )
  })

  it('Select signals error via color class + aria-invalid AND role="alert" text', () => {
    fc.assert(
      fc.property(errorArb, (error) => {
        const { container, unmount } = render(
          <Select label="Choice" error={error} options={selectOptions} />
        )

        const select = container.querySelector('select') as HTMLSelectElement

        // Channel 1 — color change.
        expect(select.className).toContain('error')
        expect(select.getAttribute('aria-invalid')).toBe('true')

        // Channel 2 — text.
        const alert = container.querySelector('[role="alert"]') as HTMLElement
        expect(alert).not.toBeNull()
        expect(alert.textContent).toBe(error)

        unmount()
      }),
      { numRuns: 150 }
    )
  })

  it('Alert severity="error" signals error via color class AND icon + text (not color alone)', () => {
    fc.assert(
      fc.property(errorArb, (message) => {
        const { container, unmount } = render(
          <Alert severity="error">{message}</Alert>
        )

        const alert = container.firstElementChild as HTMLElement

        // Channel 1 — color change: the error CSS Module class token carries
        // the semantic error left-border color + light background tint.
        expect(alert.className).toContain('error')

        // Channel 2 — non-color signals: an icon (svg) is rendered AND the
        // message text content is present, so status is never color-only.
        expect(alert.querySelector('svg')).not.toBeNull()
        expect(alert.textContent).toContain(message)

        unmount()
      }),
      { numRuns: 150 }
    )
  })
})
