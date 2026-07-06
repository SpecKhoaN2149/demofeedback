import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import AdminLayout from './AdminLayout'
import { AuthProvider } from '../../../context/AuthContext'

const renderLayout = (path = '/admin/dashboard') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AdminLayout>
          <div data-testid="admin-content">Dashboard content</div>
        </AdminLayout>
      </AuthProvider>
    </MemoryRouter>
  )

describe('AdminLayout', () => {
  it('renders its children in the content area', () => {
    renderLayout()
    const content = screen.getByTestId('admin-content')
    expect(content).toBeInTheDocument()
    expect(content).toHaveTextContent('Dashboard content')
  })

  it('composes the admin sidebar navigation', () => {
    renderLayout()
    expect(
      screen.getByRole('navigation', { name: /admin navigation/i })
    ).toBeInTheDocument()
  })

  it('renders the admin sidebar navigation links', () => {
    renderLayout()
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Review Queue')).toBeInTheDocument()
    expect(screen.getByText('Tickets')).toBeInTheDocument()
    expect(screen.getByText('Marketing Log')).toBeInTheDocument()
    expect(screen.getByText('Trend Analysis')).toBeInTheDocument()
  })

  it('wraps content in a main landmark', () => {
    renderLayout()
    expect(screen.getByRole('main')).toHaveTextContent('Dashboard content')
  })
})
