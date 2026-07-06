import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import Alert, { type AlertProps } from './Alert'

// Feature: spectrum-ui-redesign, Property 7: Alert severity determines colors and ARIA role
//
// For any valid Alert severity (success, warning, error, info), the rendered
// Alert SHALL apply the corresponding severity CSS Module class token (which,
// in Alert.module.css, encodes the semantic left-border color and the light
// background tint), AND set the element role to "alert" for error/warning
// severities or "status" for success/info severities.
//
// jsdom does not resolve CSS Module stylesheet values into computed styles, so
// we assert on the presence of the severity class token (which carries the
// color mapping) rather than the computed border/background color values.
//
// Validates: Requirements 7.1, 7.2, 7.3

const severities: AlertProps['severity'][] = [
  'success',
  'warning',
  'error',
  'info',
]

// Severity → expected ARIA role. Error/warning are assertive ("alert"),
// success/info are polite status messages ("status").
const expectedRole: Record<AlertProps['severity'], 'alert' | 'status'> = {
  success: 'status',
  warning: 'alert',
  error: 'alert',
  info: 'status',
}

describe('Alert severity rendering (property-based)', () => {
  it('applies the severity class token and correct ARIA role for any severity', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...severities),
        // Random children text (may be empty).
        fc.string(),
        (severity, childrenText) => {
          const { container, unmount } = render(
            <Alert severity={severity}>{childrenText}</Alert>
          )

          const el = container.firstElementChild as HTMLElement

          // CSS Modules hash class names, so assert on the substring token.
          // The severity token carries the semantic border color + light tint.
          expect(el.className).toContain(severity)

          // ARIA role mapping: alert for error/warning, status for success/info.
          expect(el.getAttribute('role')).toBe(expectedRole[severity])

          unmount()
        }
      ),
      { numRuns: 200 }
    )
  })
})
