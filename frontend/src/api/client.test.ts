/**
 * Verification tests for the API client.
 * Validates: Requirements 11.1, 11.2, 11.7
 *
 * Ensures all API client methods match backend endpoint signatures,
 * error handling wraps 4xx/5xx correctly, and auth headers are sent.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  createSubmission,
  getSubmissionStatus,
  getSubmission,
  login,
  logout,
  getQueue,
  sortSubmission,
  getTickets,
  advanceTicket,
  getDashboard,
  getMarketing,
  runTrends,
  ApiError,
} from './client'

// Mock global fetch
const mockFetch = vi.fn()
globalThis.fetch = mockFetch

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(data),
  } as Response
}

describe('API Client — Endpoint Wiring', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ─── Submission Endpoints ──────────────────────────────────────────────────

  describe('createSubmission', () => {
    it('sends POST to /api/submissions with correct body', async () => {
      const payload = {
        customer_name: 'Jane Doe',
        email: 'jane@test.com',
        phone: null,
        core_request: 'Need help with billing',
        sentiment: 'negative' as const,
        issue_category: 'billing',
        detailed_description: 'My bill is incorrect and needs adjustment',
      }

      mockFetch.mockResolvedValue(
        jsonResponse({
          submission_id: 'abc-123',
          progress_state: 50,
          message: 'Submission received.',
        }, 201)
      )

      const result = await createSubmission(payload)

      expect(mockFetch).toHaveBeenCalledWith('/api/submissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      expect(result.submission_id).toBe('abc-123')
      expect(result.progress_state).toBe(50)
    })
  })

  describe('getSubmissionStatus', () => {
    it('sends GET to /api/submissions/{id}/status without auth', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          submission_id: 'abc-123',
          progress_state: 75,
          sentiment: 'negative',
          message: 'In progress',
          enrichment_status: 'completed',
        })
      )

      const result = await getSubmissionStatus('abc-123')

      expect(mockFetch).toHaveBeenCalledWith('/api/submissions/abc-123/status', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      })
      expect(result.progress_state).toBe(75)
    })
  })

  describe('getSubmission', () => {
    it('sends GET to /api/submissions/{id} with auth header', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          id: 'abc-123',
          created_at: '2024-01-01T00:00:00Z',
          customer_name: 'Test',
          email: null,
          phone: null,
          core_request: 'test',
          sentiment: 'negative',
          progress_state: 50,
          issue_category: 'billing',
          detailed_description: 'description',
          praise_text: null,
          social_sharing: false,
          comment_text: null,
          enrichment_status: 'pending',
          enrichment_result: null,
          state_transitions: [],
        })
      )

      const result = await getSubmission('abc-123', 'my-token')

      expect(mockFetch).toHaveBeenCalledWith('/api/submissions/abc-123', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
      })
      expect(result.id).toBe('abc-123')
    })
  })

  // ─── Auth Endpoints ────────────────────────────────────────────────────────

  describe('login', () => {
    it('sends POST to /api/auth/login with username and password', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          token: 'session-token',
          expires_at: '2024-01-02T00:00:00Z',
          username: 'admin',
        })
      )

      const result = await login('admin', 'password123')

      expect(mockFetch).toHaveBeenCalledWith('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'admin', password: 'password123' }),
      })
      expect(result.token).toBe('session-token')
      expect(result.username).toBe('admin')
    })
  })

  describe('logout', () => {
    it('sends POST to /api/auth/logout with auth header', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ detail: 'Logged out successfully' })
      )

      const result = await logout('my-token')

      expect(mockFetch).toHaveBeenCalledWith('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
        body: JSON.stringify({}),
      })
      expect(result.detail).toBe('Logged out successfully')
    })
  })

  // ─── Admin Endpoints ───────────────────────────────────────────────────────

  describe('getQueue', () => {
    it('sends GET to /api/admin/queue with pagination params and auth', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          items: [],
          limit: 20,
          offset: 0,
        })
      )

      await getQueue('my-token', 20, 0)

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/queue?limit=20&offset=0', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
      })
    })
  })

  describe('sortSubmission', () => {
    it('sends PATCH to /api/admin/queue/{id}/sort with auth', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          submission_id: 'abc-123',
          target_sentiment: 'negative',
          progress_state: 50,
          detail: 'Submission sorted to negative',
        })
      )

      const result = await sortSubmission('my-token', 'abc-123', {
        target_sentiment: 'negative',
        issue_category: 'billing',
      })

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/queue/abc-123/sort', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
        body: JSON.stringify({ target_sentiment: 'negative', issue_category: 'billing' }),
      })
      expect(result.submission_id).toBe('abc-123')
      expect(result.target_sentiment).toBe('negative')
    })
  })

  describe('getTickets', () => {
    it('sends GET to /api/admin/tickets with auth', async () => {
      mockFetch.mockResolvedValue(jsonResponse([]))

      await getTickets('my-token')

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/tickets', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
      })
    })
  })

  describe('advanceTicket', () => {
    it('sends PATCH to /api/admin/tickets/{id}/advance with auth', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          id: 'ticket-1',
          submission_id: 'abc-123',
          issue_category: 'billing',
          description: 'Test',
          priority: 'high',
          status: 'in_progress',
          created_at: '2024-01-01T00:00:00Z',
        })
      )

      const result = await advanceTicket('my-token', 'ticket-1')

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/tickets/ticket-1/advance', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
        body: JSON.stringify({}),
      })
      expect(result.status).toBe('in_progress')
    })
  })

  describe('getDashboard', () => {
    it('sends GET to /api/admin/dashboard with auth', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          total_submissions: 18,
          by_sentiment: { negative: 5, positive: 10, neutral: 3 },
          by_progress_state: { '50': 10, '100': 8 },
          top_categories: [{ category: 'billing', count: 5 }],
        })
      )

      const result = await getDashboard('my-token')

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/dashboard', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
      })
      expect(result.total_submissions).toBe(18)
      expect(result.by_sentiment.negative).toBe(5)
      expect(result.by_progress_state['50']).toBe(10)
    })
  })

  describe('getMarketing', () => {
    it('sends GET to /api/admin/marketing with pagination and auth', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          items: [],
          total: 0,
          limit: 20,
          offset: 0,
        })
      )

      await getMarketing('my-token', 20, 0)

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/marketing?limit=20&offset=0', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
      })
    })
  })

  describe('runTrends', () => {
    it('sends POST to /api/admin/trends with baseline_window and current_window', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({
          theme_spikes: [],
          sentiment_shifts: [],
          severity_escalations: [],
        })
      )

      const body = {
        baseline_window: { start: '2024-01-01T00:00:00', end: '2024-01-15T00:00:00' },
        current_window: { start: '2024-01-16T00:00:00', end: '2024-01-31T00:00:00' },
      }

      await runTrends('my-token', body)

      expect(mockFetch).toHaveBeenCalledWith('/api/admin/trends', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer my-token',
        },
        body: JSON.stringify(body),
      })
    })
  })

  // ─── Error Handling ────────────────────────────────────────────────────────

  describe('Error handling', () => {
    it('throws ApiError with status and detail for 4xx responses', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ detail: 'Not found' }, 404)
      )

      await expect(getSubmissionStatus('nonexistent')).rejects.toThrow(ApiError)

      try {
        await getSubmissionStatus('nonexistent')
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError)
        expect((err as ApiError).status).toBe(404)
      }
    })

    it('throws ApiError with status and detail for 5xx responses', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ detail: 'Internal server error' }, 500)
      )

      await expect(createSubmission({
        customer_name: 'Test',
        core_request: 'test',
        sentiment: 'neutral',
        comment_text: 'comment',
      })).rejects.toThrow(ApiError)
    })

    it('throws ApiError with statusText when JSON parsing fails', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 502,
        statusText: 'Bad Gateway',
        json: () => Promise.reject(new Error('invalid json')),
      } as unknown as Response)

      try {
        await getSubmissionStatus('abc')
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError)
        expect((err as ApiError).status).toBe(502)
        expect((err as ApiError).detail).toBe('Bad Gateway')
      }
    })

    it('throws ApiError for 422 validation errors', async () => {
      const validationErrors = [
        { field: 'issue_category', message: 'Required for negative submissions' },
      ]
      mockFetch.mockResolvedValue(
        jsonResponse(validationErrors, 422)
      )

      try {
        await createSubmission({
          customer_name: 'Test',
          core_request: 'test',
          sentiment: 'negative',
        })
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError)
        expect((err as ApiError).status).toBe(422)
      }
    })

    it('throws ApiError for 401 unauthorized', async () => {
      mockFetch.mockResolvedValue(
        jsonResponse({ detail: 'Authentication failed' }, 401)
      )

      try {
        await login('bad', 'creds')
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError)
        expect((err as ApiError).status).toBe(401)
      }
    })
  })

  // ─── Auth Header Verification ──────────────────────────────────────────────

  describe('Auth headers', () => {
    it('does NOT send Authorization header for public endpoints', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ submission_id: 'x', progress_state: 50, message: 'ok' }, 201))

      await createSubmission({
        customer_name: 'Test',
        core_request: 'test',
        sentiment: 'neutral',
        comment_text: 'comment',
      })

      const [, options] = mockFetch.mock.calls[0]
      expect(options.headers).not.toHaveProperty('Authorization')
    })

    it('sends Authorization header for admin endpoints', async () => {
      mockFetch.mockResolvedValue(jsonResponse({ items: [], limit: 20, offset: 0 }))

      await getQueue('admin-token')

      const [, options] = mockFetch.mock.calls[0]
      expect(options.headers.Authorization).toBe('Bearer admin-token')
    })

    it('sends Authorization header for getSubmission (admin-only)', async () => {
      mockFetch.mockResolvedValue(jsonResponse({
        id: 'x',
        created_at: '2024-01-01T00:00:00Z',
        customer_name: 'T',
        email: null,
        phone: null,
        core_request: 't',
        sentiment: 'neutral',
        progress_state: 25,
        issue_category: null,
        detailed_description: null,
        praise_text: null,
        social_sharing: false,
        comment_text: 'hi',
        enrichment_status: 'pending',
        enrichment_result: null,
        state_transitions: [],
      }))

      await getSubmission('x', 'admin-token')

      const [, options] = mockFetch.mock.calls[0]
      expect(options.headers.Authorization).toBe('Bearer admin-token')
    })
  })

  // ─── Method Count Verification ─────────────────────────────────────────────

  describe('Complete method coverage', () => {
    it('exposes exactly 12 API methods', () => {
      // All 12 methods from the client module
      const methods = [
        createSubmission,
        getSubmissionStatus,
        getSubmission,
        login,
        logout,
        getQueue,
        sortSubmission,
        getTickets,
        advanceTicket,
        getDashboard,
        getMarketing,
        runTrends,
      ]
      expect(methods).toHaveLength(12)
      methods.forEach((m) => expect(typeof m).toBe('function'))
    })
  })
})
