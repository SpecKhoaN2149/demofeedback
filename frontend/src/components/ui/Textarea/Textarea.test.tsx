import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Textarea from './Textarea'

describe('Textarea', () => {
  it('renders a label linked to the textarea', () => {
    render(<Textarea label="Comments" />)
    const textarea = screen.getByLabelText('Comments')
    expect(textarea).toBeInTheDocument()
    expect(textarea.tagName).toBe('TEXTAREA')
  })

  it('applies the rows prop for height configuration', () => {
    render(<Textarea label="Comments" rows={8} />)
    const textarea = screen.getByLabelText('Comments')
    expect(textarea).toHaveAttribute('rows', '8')
  })

  it('does not set aria-invalid when there is no error', () => {
    render(<Textarea label="Feedback" />)
    const textarea = screen.getByLabelText('Feedback')
    expect(textarea).not.toHaveAttribute('aria-invalid')
  })

  it('renders the error message and sets error accessibility attributes', () => {
    render(<Textarea label="Feedback" error="Feedback is required" />)
    const textarea = screen.getByLabelText('Feedback')

    expect(textarea).toHaveAttribute('aria-invalid', 'true')

    const message = screen.getByRole('alert')
    expect(message).toHaveTextContent('Feedback is required')

    // aria-describedby links the textarea to the error message element.
    const describedBy = textarea.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(message).toHaveAttribute('id', describedBy as string)
  })

  it('renders help text and links it when there is no error', () => {
    render(<Textarea label="Notes" helpText="Optional additional detail" />)
    const textarea = screen.getByLabelText('Notes')
    const help = screen.getByText('Optional additional detail')

    const describedBy = textarea.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(help).toHaveAttribute('id', describedBy as string)
    expect(textarea).not.toHaveAttribute('aria-invalid')
  })

  it('prioritizes the error message over help text', () => {
    render(
      <Textarea
        label="Notes"
        helpText="Optional additional detail"
        error="Notes are invalid"
      />
    )
    expect(screen.getByText('Notes are invalid')).toBeInTheDocument()
    expect(
      screen.queryByText('Optional additional detail')
    ).not.toBeInTheDocument()
  })

  it('forwards native textarea props', () => {
    render(
      <Textarea label="Message" placeholder="Type here" maxLength={500} />
    )
    const textarea = screen.getByLabelText('Message')
    expect(textarea).toHaveAttribute('placeholder', 'Type here')
    expect(textarea).toHaveAttribute('maxlength', '500')
  })
})
