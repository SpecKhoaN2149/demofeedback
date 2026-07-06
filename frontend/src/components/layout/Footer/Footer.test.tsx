import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import Footer from './Footer'

const renderFooter = (props?: { className?: string }) =>
  render(
    <MemoryRouter>
      <Footer {...props} />
    </MemoryRouter>
  )

describe('Footer', () => {
  it('renders the copyright text with the current year', () => {
    const currentYear = new Date().getFullYear()
    renderFooter()
    expect(
      screen.getByText(`© ${currentYear} Charter Communications, Inc.`)
    ).toBeInTheDocument()
  })

  it('renders the Terms of Service link', () => {
    renderFooter()
    const link = screen.getByRole('link', { name: 'Terms of Service' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/terms')
  })

  it('renders the Privacy Policy link', () => {
    renderFooter()
    const link = screen.getByRole('link', { name: 'Privacy Policy' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/privacy')
  })

  it('renders a footer landmark', () => {
    renderFooter()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
  })

  it('applies a custom className when provided', () => {
    renderFooter({ className: 'extra' })
    expect(screen.getByRole('contentinfo').className).toContain('extra')
  })
})
