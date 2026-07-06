import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Badge from './Badge'

describe('Badge', () => {
  it('renders its children', () => {
    render(<Badge color="success">Active</Badge>)
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it.each(['success', 'warning', 'error', 'info', 'neutral'] as const)(
    'applies the %s color class',
    (color) => {
      render(<Badge color={color}>Label</Badge>)
      expect(screen.getByText('Label').className).toContain(color)
    }
  )

  it('always applies the base badge class', () => {
    render(<Badge color="info">Base</Badge>)
    expect(screen.getByText('Base').className).toContain('badge')
  })

  it('merges a custom className', () => {
    render(
      <Badge color="neutral" className="extra">
        Custom
      </Badge>
    )
    const badge = screen.getByText('Custom')
    expect(badge.className).toContain('extra')
    expect(badge.className).toContain('neutral')
  })

  it('renders each color with a distinct class', () => {
    const { rerender } = render(<Badge color="success">X</Badge>)
    const successClass = screen.getByText('X').className
    rerender(<Badge color="error">X</Badge>)
    const errorClass = screen.getByText('X').className
    expect(successClass).not.toEqual(errorClass)
  })
})
