import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import AdminSidebar, { ADMIN_NAV_LINKS } from './AdminSidebar'

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AdminSidebar />
    </MemoryRouter>
  )

describe('AdminSidebar', () => {
  it('renders all navigation links', () => {
    renderAt('/admin/dashboard')
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Review Queue')).toBeInTheDocument()
    expect(screen.getByText('Tickets')).toBeInTheDocument()
    expect(screen.getByText('Marketing Log')).toBeInTheDocument()
    expect(screen.getByText('Trend Analysis')).toBeInTheDocument()
  })

  it('points each link at its admin route', () => {
    renderAt('/admin/dashboard')
    for (const { label, path } of ADMIN_NAV_LINKS) {
      expect(screen.getByText(label).closest('a')).toHaveAttribute('href', path)
    }
  })

  it('exposes an accessible navigation landmark', () => {
    renderAt('/admin/dashboard')
    expect(
      screen.getByRole('navigation', { name: /admin navigation/i })
    ).toBeInTheDocument()
  })

  it('applies the active class to the link matching the current route', () => {
    renderAt('/admin/queue')
    const activeLink = screen.getByText('Review Queue')
    expect(activeLink.className).toContain('active')
  })

  it('does not mark non-current links as active', () => {
    renderAt('/admin/queue')
    const inactiveLink = screen.getByText('Dashboard')
    expect(inactiveLink.className).not.toContain('active')
  })
})
