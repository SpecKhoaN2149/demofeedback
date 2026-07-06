// Feature: spectrum-ui-redesign, Property 2: Disabled Button behavior
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import fc from 'fast-check'
import Button from './Button'

/**
 * Property 2: Disabled Button behavior
 *
 * For any Button configuration (any variant, any size, any label text), when the
 * `disabled` prop is `true`, the rendered Button SHALL NOT trigger onClick handlers
 * when clicked and SHALL be marked disabled.
 *
 * Validates: Requirements 3.9
 */

const variants = ['primary', 'secondary', 'outline', 'ghost'] as const
const sizes = ['small', 'medium', 'large'] as const

describe('Button disabled behavior (Property 2)', () => {
  it('never fires onClick and is marked disabled for any config with disabled=true', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...variants),
        fc.constantFrom(...sizes),
        fc.string({ minLength: 1, maxLength: 40 }),
        (variant, size, label) => {
          const handleClick = vi.fn()

          render(
            <Button
              variant={variant}
              size={size}
              disabled
              onClick={handleClick}
            >
              {label}
            </Button>
          )

          try {
            const button = screen.getByRole('button')

            // The button must report itself as disabled.
            expect(button).toBeDisabled()
            expect(button.hasAttribute('disabled')).toBe(true)

            // Clicking a disabled button must not fire the handler.
            fireEvent.click(button)
            expect(handleClick).not.toHaveBeenCalled()
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
