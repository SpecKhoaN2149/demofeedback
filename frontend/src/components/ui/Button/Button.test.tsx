import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import Button from './Button'

describe('Button', () => {
  it('renders its children', () => {
    render(<Button>Click me</Button>)
    expect(
      screen.getByRole('button', { name: 'Click me' })
    ).toBeInTheDocument()
  })

  it('applies primary variant and medium size by default', () => {
    render(<Button>Default</Button>)
    const button = screen.getByRole('button', { name: 'Default' })
    expect(button.className).toContain('primary')
    expect(button.className).toContain('medium')
  })

  it.each(['primary', 'secondary', 'outline', 'ghost'] as const)(
    'applies the %s variant class',
    (variant) => {
      render(<Button variant={variant}>Variant</Button>)
      expect(screen.getByRole('button').className).toContain(variant)
    }
  )

  it.each(['small', 'medium', 'large'] as const)(
    'applies the %s size class',
    (size) => {
      render(<Button size={size}>Size</Button>)
      expect(screen.getByRole('button').className).toContain(size)
    }
  )

  it('applies the fullWidth class when fullWidth is true', () => {
    render(<Button fullWidth>Wide</Button>)
    expect(screen.getByRole('button').className).toContain('fullWidth')
  })

  it('does not apply the fullWidth class by default', () => {
    render(<Button>Normal</Button>)
    expect(screen.getByRole('button').className).not.toContain('fullWidth')
  })

  it('defaults the button type to "button"', () => {
    render(<Button>Type</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })

  it('forwards additional props and custom className', () => {
    render(
      <Button className="extra" data-testid="btn" aria-label="labelled">
        Props
      </Button>
    )
    const button = screen.getByTestId('btn')
    expect(button.className).toContain('extra')
    expect(button).toHaveAttribute('aria-label', 'labelled')
  })

  it('fires onClick when enabled', () => {
    const handleClick = vi.fn()
    render(<Button onClick={handleClick}>Enabled</Button>)
    fireEvent.click(screen.getByRole('button'))
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('does not fire onClick when disabled', () => {
    const handleClick = vi.fn()
    render(
      <Button disabled onClick={handleClick}>
        Disabled
      </Button>
    )
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(handleClick).not.toHaveBeenCalled()
  })
})
