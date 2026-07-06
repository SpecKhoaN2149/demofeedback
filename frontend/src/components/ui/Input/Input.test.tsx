import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Input from './Input'

describe('Input', () => {
  it('renders a label linked to the input', () => {
    render(<Input label="Full name" />)
    const input = screen.getByLabelText('Full name')
    expect(input).toBeInTheDocument()
    expect(input.tagName).toBe('INPUT')
  })

  it('does not set aria-invalid when there is no error', () => {
    render(<Input label="Email" />)
    const input = screen.getByLabelText('Email')
    expect(input).not.toHaveAttribute('aria-invalid')
  })

  it('renders the error message and sets error accessibility attributes', () => {
    render(<Input label="Email" error="Email is required" />)
    const input = screen.getByLabelText('Email')

    expect(input).toHaveAttribute('aria-invalid', 'true')

    const message = screen.getByRole('alert')
    expect(message).toHaveTextContent('Email is required')

    // aria-describedby links the input to the error message element.
    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(message).toHaveAttribute('id', describedBy as string)
  })

  it('renders help text and links it when there is no error', () => {
    render(<Input label="Phone" helpText="Include country code" />)
    const input = screen.getByLabelText('Phone')
    const help = screen.getByText('Include country code')

    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(help).toHaveAttribute('id', describedBy as string)
    expect(input).not.toHaveAttribute('aria-invalid')
  })

  it('prioritizes the error message over help text', () => {
    render(
      <Input label="Phone" helpText="Include country code" error="Invalid phone" />
    )
    expect(screen.getByText('Invalid phone')).toBeInTheDocument()
    expect(screen.queryByText('Include country code')).not.toBeInTheDocument()
  })

  it('forwards native input props', () => {
    render(<Input label="Email" type="email" placeholder="you@example.com" />)
    const input = screen.getByLabelText('Email')
    expect(input).toHaveAttribute('type', 'email')
    expect(input).toHaveAttribute('placeholder', 'you@example.com')
  })
})
