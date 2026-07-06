import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import Header, { HEADER_NAV_LINKS } from './Header'

const renderAt = (path = '/') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Header />
    </MemoryRouter>
  )

describe('Header', () => {
  it('renders the Spectrum logo linking home', () => {
    renderAt()
    expect(screen.getByLabelText('Spectrum home')).toHaveAttribute('href', '/')
    // SpectrumLogo exposes an accessible name of "Spectrum".
    expect(screen.getByRole('img', { name: 'Spectrum' })).toBeInTheDocument()
  })

  it('renders all navigation links pointing at their routes', () => {
    renderAt()
    for (const { label, path } of HEADER_NAV_LINKS) {
      // Links appear in both desktop and mobile navs; every instance should
      // point at the same route.
      const matches = screen.getAllByRole('link', { name: label })
      expect(matches.length).toBeGreaterThan(0)
      for (const link of matches) {
        expect(link).toHaveAttribute('href', path)
      }
    }
  })

  it('exposes the primary navigation landmark', () => {
    renderAt()
    expect(
      screen.getByRole('navigation', { name: /primary/i })
    ).toBeInTheDocument()
  })

  it('marks the toggle button collapsed by default with an accessible label', () => {
    renderAt()
    const toggle = screen.getByRole('button', { name: /open navigation menu/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveAttribute('aria-controls', 'mobile-navigation')
  })

  it('opens the mobile menu when the toggle is clicked', () => {
    renderAt()
    const toggle = screen.getByRole('button', { name: /open navigation menu/i })
    fireEvent.click(toggle)

    const openToggle = screen.getByRole('button', {
      name: /close navigation menu/i,
    })
    expect(openToggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('mobile-menu-overlay')).toBeInTheDocument()
  })

  it('closes the mobile menu on ESC and returns focus to the toggle', () => {
    renderAt()
    const toggle = screen.getByRole('button', { name: /open navigation menu/i })
    fireEvent.click(toggle)
    expect(
      screen.getByRole('button', { name: /close navigation menu/i })
    ).toHaveAttribute('aria-expanded', 'true')

    fireEvent.keyDown(document, { key: 'Escape' })

    const closedToggle = screen.getByRole('button', {
      name: /open navigation menu/i,
    })
    expect(closedToggle).toHaveAttribute('aria-expanded', 'false')
    expect(closedToggle).toHaveFocus()
  })

  it('closes the mobile menu when the overlay is clicked and restores focus', () => {
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: /open navigation menu/i }))

    fireEvent.click(screen.getByTestId('mobile-menu-overlay'))

    const closedToggle = screen.getByRole('button', {
      name: /open navigation menu/i,
    })
    expect(closedToggle).toHaveAttribute('aria-expanded', 'false')
    expect(closedToggle).toHaveFocus()
    expect(screen.queryByTestId('mobile-menu-overlay')).not.toBeInTheDocument()
  })

  it('closes the mobile menu when a mobile nav link is activated', () => {
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: /open navigation menu/i }))

    const mobileNav = screen.getByRole('navigation', { name: /mobile/i })
    const homeLink = within(mobileNav).getByRole('link', { name: 'Home' })
    fireEvent.click(homeLink)

    expect(
      screen.getByRole('button', { name: /open navigation menu/i })
    ).toHaveAttribute('aria-expanded', 'false')
  })
})
