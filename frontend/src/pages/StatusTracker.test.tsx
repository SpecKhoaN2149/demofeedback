import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import StatusTracker, { getStatusMessage } from './StatusTracker'

// Mock the usePolling hook
vi.mock('../hooks/usePolling', () => ({
  usePolling: vi.fn(),
}))

import { usePolling } from '../hooks/usePolling'

const mockedUsePolling = vi.mocked(usePolling)

function renderStatusTracker(id?: string) {
  const path = id ? `/status/${id}` : '/status/'
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/status/:id" element={<StatusTracker />} />
        <Route path="/status/" element={<StatusTracker />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('StatusTracker', () => {
  beforeEach(() => {
    mockedUsePolling.mockReset()
  })

  it('displays error when submission ID is missing', () => {
    mockedUsePolling.mockReturnValue({
      status: null,
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    render(
      <MemoryRouter initialEntries={['/status/']}>
        <Routes>
          <Route path="/status/" element={<StatusTracker />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Submission not found')).toBeInTheDocument()
  })

  it('shows loading state before first response', () => {
    mockedUsePolling.mockReturnValue({
      status: null,
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    expect(screen.getByText('Checking submission status…')).toBeInTheDocument()
  })

  it('displays progress bar at 25% with pulsing animation for neutral awaiting review', () => {
    mockedUsePolling.mockReturnValue({
      status: {
        submission_id: 'abc-123',
        progress_state: 25,
        sentiment: 'neutral',
        message: 'Awaiting Review',
        enrichment_status: 'pending',
      },
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    const progressBar = screen.getByRole('progressbar')
    expect(progressBar).toHaveAttribute('aria-valuenow', '25')
    const fill = progressBar.firstElementChild as HTMLElement
    expect(fill.className).toMatch(/pulsing/)
    expect(screen.getByText('Awaiting Review')).toBeInTheDocument()
  })

  it('displays progress bar at 50% for negative submission', () => {
    mockedUsePolling.mockReturnValue({
      status: {
        submission_id: 'abc-123',
        progress_state: 50,
        sentiment: 'negative',
        message: 'Spectrum is working on this.',
        enrichment_status: 'pending',
      },
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    const progressBar = screen.getByRole('progressbar')
    expect(progressBar).toHaveAttribute('aria-valuenow', '50')
    const fill = progressBar.firstElementChild as HTMLElement
    expect(fill.className).not.toMatch(/pulsing/)
    expect(screen.getByText('Spectrum is working on this.')).toBeInTheDocument()
  })

  it('displays progress bar at 75% with resolution message', () => {
    mockedUsePolling.mockReturnValue({
      status: {
        submission_id: 'abc-123',
        progress_state: 75,
        sentiment: 'negative',
        message: 'Almost there — resolution in progress.',
        enrichment_status: 'completed',
      },
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    const progressBar = screen.getByRole('progressbar')
    expect(progressBar).toHaveAttribute('aria-valuenow', '75')
    expect(screen.getByText('Almost there — resolution in progress.')).toBeInTheDocument()
  })

  it('displays progress bar at 100% with positive completion message', () => {
    mockedUsePolling.mockReturnValue({
      status: {
        submission_id: 'abc-123',
        progress_state: 100,
        sentiment: 'positive',
        message: 'Praise received & noted!',
        enrichment_status: 'completed',
      },
      error: null,
      isComplete: true,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    const progressBar = screen.getByRole('progressbar')
    expect(progressBar).toHaveAttribute('aria-valuenow', '100')
    const fill = progressBar.firstElementChild as HTMLElement
    expect(fill.className).toMatch(/complete/)
    expect(screen.getByText('Praise received & noted!')).toBeInTheDocument()
    expect(screen.getByText('Thank you for your feedback!')).toBeInTheDocument()
  })

  it('displays connection lost message with retry button', () => {
    const retryFn = vi.fn()
    mockedUsePolling.mockReturnValue({
      status: {
        submission_id: 'abc-123',
        progress_state: 50,
        sentiment: 'negative',
        message: 'Spectrum is working on this.',
        enrichment_status: 'pending',
      },
      error: new Error('Network error'),
      isComplete: false,
      connectionLost: true,
      retry: retryFn,
    })

    renderStatusTracker('abc-123')
    expect(screen.getByText('Connection to the server has been lost.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('calls retry when retry button is clicked', () => {
    const retryFn = vi.fn()
    mockedUsePolling.mockReturnValue({
      status: null,
      error: new Error('Network error'),
      isComplete: false,
      connectionLost: true,
      retry: retryFn,
    })

    renderStatusTracker('abc-123')
    screen.getByRole('button', { name: 'Retry' }).click()
    expect(retryFn).toHaveBeenCalledOnce()
  })

  it('passes the submission ID from URL params to usePolling', () => {
    mockedUsePolling.mockReturnValue({
      status: null,
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('my-submission-id')
    expect(mockedUsePolling).toHaveBeenCalledWith('my-submission-id')
  })
})

describe('getStatusMessage', () => {
  it('returns "Awaiting Review" for 25% progress', () => {
    expect(getStatusMessage(25, 'neutral')).toBe('Awaiting Review')
  })

  it('returns "Spectrum is working on this." for 50% progress', () => {
    expect(getStatusMessage(50, 'negative')).toBe('Spectrum is working on this.')
  })

  it('returns "Almost there — resolution in progress." for 75% progress', () => {
    expect(getStatusMessage(75, 'negative')).toBe('Almost there — resolution in progress.')
  })

  it('returns "Praise received & noted!" for 100% positive', () => {
    expect(getStatusMessage(100, 'positive')).toBe('Praise received & noted!')
  })

  it('returns "Your issue has been resolved." for 100% negative', () => {
    expect(getStatusMessage(100, 'negative')).toBe('Your issue has been resolved.')
  })

  it('returns "Your issue has been resolved." for 100% neutral', () => {
    expect(getStatusMessage(100, 'neutral')).toBe('Your issue has been resolved.')
  })

  it('returns default message for unknown progress states', () => {
    expect(getStatusMessage(60, 'negative')).toBe('Spectrum is working on this.')
  })
})
