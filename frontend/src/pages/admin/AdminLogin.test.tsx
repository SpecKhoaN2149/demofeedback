import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AdminLogin from './AdminLogin'
import { AuthProvider } from '../../context/AuthContext'

// Mock the API client
vi.mock('../../api/client', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(`API error ${status}: ${detail}`)
      this.status = status
      this.detail = detail
      this.name = 'ApiError'
    }
  },
}))

import { login as apiLogin, ApiError, type LoginResponse } from '../../api/client'

const mockedApiLogin = vi.mocked(apiLogin)

function renderAdminLogin() {
  return render(
    <MemoryRouter initialEntries={['/admin/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin/dashboard" element={<div>Dashboard</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  )
}

describe('AdminLogin', () => {
  beforeEach(() => {
    mockedApiLogin.mockReset()
    localStorage.clear()
  })

  it('renders login form with username and password fields', () => {
    renderAdminLogin()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument()
  })

  it('redirects to /admin/dashboard on successful login', async () => {
    mockedApiLogin.mockResolvedValue({
      token: 'test-token',
      expires_at: '2025-12-31T00:00:00Z',
      username: 'admin',
    })

    renderAdminLogin()

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))

    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeInTheDocument()
    })
  })

  it('displays generic error message on auth failure', async () => {
    mockedApiLogin.mockRejectedValue(new ApiError(401, 'Authentication failed'))

    renderAdminLogin()

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Authentication failed. Please check your credentials.'
      )
    })
  })

  it('displays network error message on connection failure', async () => {
    mockedApiLogin.mockRejectedValue(new Error('Failed to fetch'))

    renderAdminLogin()

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Unable to connect to the server. Please try again.'
      )
    })
  })

  it('shows loading state during submission', async () => {
    let resolveLogin: (value: LoginResponse) => void
    mockedApiLogin.mockReturnValue(
      new Promise<LoginResponse>((resolve) => { resolveLogin = resolve })
    )

    renderAdminLogin()

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))

    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled()

    resolveLogin!({ token: 'test', expires_at: '2025-12-31T00:00:00Z', username: 'admin' })
    await waitFor(() => {
      expect(screen.queryByText('Signing in…')).not.toBeInTheDocument()
    })
  })
})
