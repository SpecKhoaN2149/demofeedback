import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AdminDashboard from './AdminDashboard'
import { AuthProvider } from '../../context/AuthContext'

vi.mock('../../api/client', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  getDashboard: vi.fn(),
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

import { getDashboard, ApiError } from '../../api/client'

const mockedGetDashboard = vi.mocked(getDashboard)

function renderDashboard() {
  // Set a token in localStorage so AuthContext provides it
  localStorage.setItem('auth_token', 'test-token')
  localStorage.setItem('auth_username', 'admin')
  return render(
    <MemoryRouter>
      <AuthProvider>
        <AdminDashboard />
      </AuthProvider>
    </MemoryRouter>
  )
}

describe('AdminDashboard', () => {
  beforeEach(() => {
    mockedGetDashboard.mockReset()
    localStorage.clear()
  })

  it('displays loading state initially', () => {
    mockedGetDashboard.mockReturnValue(new Promise(() => {})) // never resolves
    renderDashboard()
    expect(screen.getByText('Loading dashboard…')).toBeInTheDocument()
  })

  it('displays summary stats when data loads', async () => {
    mockedGetDashboard.mockResolvedValue({
      total_submissions: 18,
      by_sentiment: { negative: 5, positive: 10, neutral: 3 },
      by_progress_state: { '25': 3, '50': 5, '100': 10 },
      top_categories: [
        { category: 'billing', count: 3 },
        { category: 'outage', count: 2 },
      ],
    })

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('negative')).toBeInTheDocument()
    })

    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('billing — 3 submissions')).toBeInTheDocument()
    expect(screen.getByText('outage — 2 submissions')).toBeInTheDocument()
  })

  it('handles empty state with zero counts', async () => {
    mockedGetDashboard.mockResolvedValue({
      total_submissions: 0,
      by_sentiment: {},
      by_progress_state: {},
      top_categories: [],
    })

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('No submissions yet.')).toBeInTheDocument()
    })

    expect(screen.getByText('No progress data available.')).toBeInTheDocument()
    expect(screen.getByText('No negative submissions to rank.')).toBeInTheDocument()
  })

  it('displays error message on API failure', async () => {
    mockedGetDashboard.mockRejectedValue(new ApiError(500, 'Internal server error'))

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    expect(screen.getByRole('alert').textContent).toContain('Failed to load dashboard')
  })

  it('limits top categories to 5', async () => {
    mockedGetDashboard.mockResolvedValue({
      total_submissions: 20,
      by_sentiment: { negative: 20 },
      by_progress_state: { '50': 20 },
      top_categories: [
        { category: 'billing', count: 10 },
        { category: 'outage', count: 8 },
        { category: 'network_speed', count: 6 },
        { category: 'support_experience', count: 4 },
        { category: 'device_hardware', count: 2 },
        { category: 'pricing', count: 1 },
      ],
    })

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('billing — 10 submissions')).toBeInTheDocument()
    })

    // Only first 5 should render
    expect(screen.getByText('device_hardware — 2 submissions')).toBeInTheDocument()
    expect(screen.queryByText('pricing — 1 submission')).not.toBeInTheDocument()
  })
})
