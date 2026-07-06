import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import NavigationShell from './NavigationShell'

const renderShell = (children: React.ReactNode = <p>Page content</p>) =>
  render(
    <MemoryRouter>
      <NavigationShell>{children}</NavigationShell>
    </MemoryRouter>
  )

describe('NavigationShell', () => {
  it('renders the provided children within the main landmark', () => {
    renderShell(<p>Hello world</p>)
    const main = screen.getByRole('main')
    expect(main).toBeInTheDocument()
    expect(main).toHaveTextContent('Hello world')
  })

  it('renders the Header with primary navigation', () => {
    renderShell()
    // Header exposes the "Primary" navigation landmark.
    expect(
      screen.getByRole('navigation', { name: 'Primary' })
    ).toBeInTheDocument()
    // Header banner landmark is present.
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })

  it('renders the Footer with copyright text', () => {
    const currentYear = new Date().getFullYear()
    renderShell()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
    expect(
      screen.getByText(`© ${currentYear} Charter Communications, Inc.`)
    ).toBeInTheDocument()
  })

  it('applies a custom className when provided', () => {
    render(
      <MemoryRouter>
        <NavigationShell className="extra">
          <p>content</p>
        </NavigationShell>
      </MemoryRouter>
    )
    // The main landmark is nested inside the shell container that carries the class.
    const main = screen.getByRole('main')
    expect(main.parentElement?.className).toContain('extra')
  })
})
