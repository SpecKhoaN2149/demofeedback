import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import Card from './Card'

describe('Card', () => {
  it('renders children', () => {
    render(<Card>Card content</Card>)
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })

  it('is a plain container (no button role) by default', () => {
    render(<Card>Static</Card>)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('applies a custom className alongside the base class', () => {
    const { container } = render(<Card className="extra">Content</Card>)
    const el = container.firstElementChild as HTMLElement
    expect(el.className).toContain('extra')
  })

  describe('interactive mode', () => {
    it('exposes role="button" and is keyboard focusable', () => {
      render(<Card interactive>Click me</Card>)
      const card = screen.getByRole('button')
      expect(card).toBeInTheDocument()
      expect(card).toHaveAttribute('tabindex', '0')
    })

    it('triggers onClick when clicked', () => {
      const onClick = vi.fn()
      render(
        <Card interactive onClick={onClick}>
          Click me
        </Card>
      )
      fireEvent.click(screen.getByRole('button'))
      expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('triggers onClick on Enter key', () => {
      const onClick = vi.fn()
      render(
        <Card interactive onClick={onClick}>
          Activate
        </Card>
      )
      fireEvent.keyDown(screen.getByRole('button'), { key: 'Enter' })
      expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('triggers onClick on Space key', () => {
      const onClick = vi.fn()
      render(
        <Card interactive onClick={onClick}>
          Activate
        </Card>
      )
      fireEvent.keyDown(screen.getByRole('button'), { key: ' ' })
      expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('does not activate on other keys', () => {
      const onClick = vi.fn()
      render(
        <Card interactive onClick={onClick}>
          Activate
        </Card>
      )
      fireEvent.keyDown(screen.getByRole('button'), { key: 'a' })
      expect(onClick).not.toHaveBeenCalled()
    })

    it('still forwards keydown to a provided onKeyDown handler', () => {
      const onKeyDown = vi.fn()
      render(
        <Card interactive onKeyDown={onKeyDown}>
          Activate
        </Card>
      )
      fireEvent.keyDown(screen.getByRole('button'), { key: 'Enter' })
      expect(onKeyDown).toHaveBeenCalledTimes(1)
    })

    it('honors an explicit tabIndex override', () => {
      render(
        <Card interactive tabIndex={-1}>
          Content
        </Card>
      )
      expect(screen.getByRole('button')).toHaveAttribute('tabindex', '-1')
    })

    it('applies an aria-label when provided', () => {
      render(
        <Card interactive aria-label="Select negative sentiment">
          Content
        </Card>
      )
      expect(
        screen.getByRole('button', { name: 'Select negative sentiment' })
      ).toBeInTheDocument()
    })
  })

  describe('bordered mode', () => {
    it('applies the bordered class', () => {
      const { container } = render(<Card bordered>Content</Card>)
      const el = container.firstElementChild as HTMLElement
      // CSS Modules hash class names, so assert on the substring.
      expect(el.className).toContain('bordered')
    })
  })
})
