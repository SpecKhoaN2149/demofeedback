import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Select from './Select'

const options = [
  { value: 'billing', label: 'Billing' },
  { value: 'technical', label: 'Technical support' },
  { value: 'sales', label: 'Sales' },
]

describe('Select', () => {
  it('renders a label linked to the select', () => {
    render(<Select label="Category" options={options} />)
    const select = screen.getByLabelText('Category')
    expect(select).toBeInTheDocument()
    expect(select.tagName).toBe('SELECT')
  })

  it('renders an option element for each provided option', () => {
    render(<Select label="Category" options={options} />)
    const rendered = screen.getAllByRole('option')
    expect(rendered).toHaveLength(options.length)
    options.forEach((option) => {
      expect(
        screen.getByRole('option', { name: option.label })
      ).toHaveValue(option.value)
    })
  })

  it('does not set aria-invalid when there is no error', () => {
    render(<Select label="Category" options={options} />)
    const select = screen.getByLabelText('Category')
    expect(select).not.toHaveAttribute('aria-invalid')
  })

  it('renders the error message and sets error accessibility attributes', () => {
    render(
      <Select label="Category" options={options} error="Please pick a category" />
    )
    const select = screen.getByLabelText('Category')

    expect(select).toHaveAttribute('aria-invalid', 'true')

    const message = screen.getByRole('alert')
    expect(message).toHaveTextContent('Please pick a category')

    // aria-describedby links the select to the error message element.
    const describedBy = select.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(message).toHaveAttribute('id', describedBy as string)
  })

  it('forwards native select props', () => {
    render(
      <Select
        label="Category"
        options={options}
        defaultValue="technical"
        name="category"
      />
    )
    const select = screen.getByLabelText('Category')
    expect(select).toHaveAttribute('name', 'category')
    expect(select).toHaveValue('technical')
  })

  it('renders an empty select when no options are provided', () => {
    render(<Select label="Category" options={[]} />)
    const select = screen.getByLabelText('Category')
    expect(select).toBeInTheDocument()
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })
})
