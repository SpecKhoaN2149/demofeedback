// Feature: spectrum-ui-redesign, Property 3: Input error state accessibility
import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, describe, it, expect } from 'vitest'
import fc from 'fast-check'
import Input from './Input'

afterEach(() => {
  cleanup()
})

describe('Input error state accessibility (property)', () => {
  // Property 3: For any Input with a non-empty `error` string, the rendered
  // element SHALL have aria-invalid="true", SHALL render an error message
  // element containing the error text, and SHALL link the input to the error
  // message via aria-describedby.
  // Validates: Requirements 4.3
  it('links a non-empty error to the input via aria-invalid + aria-describedby', () => {
    fc.assert(
      fc.property(
        // Non-empty error strings (trimmed to guarantee visible content).
        fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0),
        // Random non-empty labels.
        fc.string({ minLength: 1, maxLength: 100 }).filter((s) => s.trim().length > 0),
        (error, label) => {
          cleanup()
          render(<Input label={label} error={error} />)

          // Query the input by role so the assertion is robust to label
          // whitespace normalization performed by getByLabelText.
          const input = screen.getByRole('textbox')

          // aria-invalid must be "true" in the error state.
          expect(input).toHaveAttribute('aria-invalid', 'true')

          // An error message element with role="alert" must contain the text.
          const message = screen.getByRole('alert')
          expect(message).toHaveTextContent(error.trim())

          // aria-describedby must point at the error element's id.
          const describedBy = input.getAttribute('aria-describedby')
          expect(describedBy).toBeTruthy()
          expect(message).toHaveAttribute('id', describedBy as string)
        }
      ),
      { numRuns: 100 }
    )
  })
})
