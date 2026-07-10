import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import StatusTracker, { buildStatusModel } from './StatusTracker'
import type { FeedbackStatus } from '../api/client'

// Mock the usePolling hook
vi.mock('../hooks/usePolling', () => ({
  usePolling: vi.fn(),
}))

import { usePolling } from '../hooks/usePolling'

const mockedUsePolling = vi.mocked(usePolling)

function makeStatus(overrides: Partial<FeedbackStatus> = {}): FeedbackStatus {
  return {
    feedback_id: 'abc-123',
    enrichment_status: 'completed',
    triage_outcome: null,
    ticket: null,
    comments: [],
    analysis_in_progress: false,
    ...overrides,
  }
}

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

  it('displays error when feedback ID is missing', () => {
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

    expect(screen.getByText('Feedback not found')).toBeInTheDocument()
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
    expect(screen.getByText('Checking feedback status…')).toBeInTheDocument()
  })

  it('shows "no ticket associated" message when feedback has no ticket', () => {
    mockedUsePolling.mockReturnValue({
      status: makeStatus({ triage_outcome: 'no_action' }),
      error: null,
      isComplete: true,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    expect(
      screen.getByText('No ticket is associated with this feedback yet.')
    ).toBeInTheDocument()
    expect(
      screen.getByText('Reviewed and retained as feedback.')
    ).toBeInTheDocument()
  })

  it('renders the linked ticket status and its comments (ascending)', () => {
    mockedUsePolling.mockReturnValue({
      status: makeStatus({
        triage_outcome: 'action_required',
        ticket: { ticket_id: 't-1', status: 'in_progress' },
        comments: [
          {
            id: 1,
            ticket_id: 't-1',
            author: 'admin',
            created_at: '2024-01-01T10:00:00Z',
            text: 'We are looking into this.',
          },
          {
            id: 2,
            ticket_id: 't-1',
            author: 'support',
            created_at: '2024-01-02T10:00:00Z',
            text: 'Fix is on the way.',
          },
        ],
      }),
      error: null,
      isComplete: true,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    expect(screen.getByText('Ticket status:')).toBeInTheDocument()
    expect(screen.getByText('In progress')).toBeInTheDocument()
    expect(screen.getByText('We are looking into this.')).toBeInTheDocument()
    expect(screen.getByText('Fix is on the way.')).toBeInTheDocument()
    expect(screen.getByText('admin')).toBeInTheDocument()
    expect(screen.getByText('support')).toBeInTheDocument()
  })

  it('indicates analysis in progress while enrichment is pending', () => {
    mockedUsePolling.mockReturnValue({
      status: makeStatus({
        enrichment_status: 'pending',
        analysis_in_progress: true,
      }),
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('abc-123')
    expect(screen.getByText('Analysis in progress')).toBeInTheDocument()
  })

  it('displays connection lost message with retry button', () => {
    const retryFn = vi.fn()
    mockedUsePolling.mockReturnValue({
      status: makeStatus({ enrichment_status: 'pending' }),
      error: new Error('Network error'),
      isComplete: false,
      connectionLost: true,
      retry: retryFn,
    })

    renderStatusTracker('abc-123')
    expect(
      screen.getByText('Connection to the server has been lost.')
    ).toBeInTheDocument()
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

  it('passes the feedback ID from URL params to usePolling', () => {
    mockedUsePolling.mockReturnValue({
      status: null,
      error: null,
      isComplete: false,
      connectionLost: false,
      retry: vi.fn(),
    })

    renderStatusTracker('my-feedback-id')
    expect(mockedUsePolling).toHaveBeenCalledWith('my-feedback-id')
  })
})

describe('buildStatusModel', () => {
  it('reports no ticket and empty comments when unlinked', () => {
    const model = buildStatusModel(
      makeStatus({ triage_outcome: 'no_action', ticket: null })
    )
    expect(model.hasTicket).toBe(false)
    expect(model.ticketStatus).toBeNull()
    expect(model.comments).toEqual([])
    expect(model.triageLabel).toBe('Reviewed and retained as feedback.')
  })

  it('exposes the linked ticket status and comments', () => {
    const comments = [
      {
        id: 1,
        ticket_id: 't-1',
        author: 'admin',
        created_at: '2024-01-01T10:00:00Z',
        text: 'hello',
      },
    ]
    const model = buildStatusModel(
      makeStatus({
        triage_outcome: 'action_required',
        ticket: { ticket_id: 't-1', status: 'resolved' },
        comments,
      })
    )
    expect(model.hasTicket).toBe(true)
    expect(model.ticketStatus).toBe('resolved')
    expect(model.comments).toEqual(comments)
  })

  it('reports analysis in progress while enrichment is pending', () => {
    const model = buildStatusModel(
      makeStatus({ enrichment_status: 'pending', analysis_in_progress: true })
    )
    expect(model.analysisInProgress).toBe(true)
    expect(model.statusLabel).toBe('Analysis in progress')
  })
})
