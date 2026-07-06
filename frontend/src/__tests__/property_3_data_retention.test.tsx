/**
 * Property 3: Data retained across page navigation
 *
 * For any valid Page 1 form data (name, email, phone, core request), when
 * navigating through sentiment selection to any Page 3 form and submitting,
 * the final submission payload SHALL include all Page 1 field values unchanged.
 *
 * **Validates: Requirements 2.5**
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import * as fc from 'fast-check'
import NegativeForm from '../pages/NegativeForm'
import PositiveForm from '../pages/PositiveForm'
import NeutralForm from '../pages/NeutralForm'
import type { SubmissionCreatePayload } from '../api/client'

// Mock the API client module
vi.mock('../api/client', () => ({
  createSubmission: vi.fn(),
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

import { createSubmission } from '../api/client'

const mockedCreateSubmission = vi.mocked(createSubmission)

// --- Generators ---

/** Generates valid customer names (1-100 chars, non-empty after trim) */
const validNameArb = fc
  .stringOf(
    fc.constantFrom(
      ...'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -'.split('')
    ),
    { minLength: 1, maxLength: 50 }
  )
  .filter((s) => s.trim().length >= 1 && s.trim().length <= 100)

/** Generates valid email addresses */
const validEmailArb = fc
  .tuple(
    fc.stringOf(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789'.split('')), {
      minLength: 1,
      maxLength: 8,
    }),
    fc.stringOf(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz'.split('')), {
      minLength: 1,
      maxLength: 8,
    }),
    fc.stringOf(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz'.split('')), {
      minLength: 2,
      maxLength: 4,
    })
  )
  .map(([local, domain, tld]) => `${local}@${domain}.${tld}`)

/** Generates valid phone numbers (7-15 digits, optional + prefix) */
const validPhoneArb = fc
  .tuple(
    fc.boolean(),
    fc.integer({ min: 7, max: 15 })
  )
  .chain(([hasPlus, len]) =>
    fc
      .stringOf(fc.constantFrom(...'0123456789'.split('')), {
        minLength: len,
        maxLength: len,
      })
      .map((digits) => (hasPlus ? `+${digits}` : digits))
  )

/** Generates valid core request text (1-100 chars, non-empty after trim) */
const validCoreRequestArb = fc
  .stringOf(
    fc.constantFrom(
      ...'abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?'.split('')
    ),
    { minLength: 1, maxLength: 80 }
  )
  .filter((s) => s.trim().length >= 1)

/** Generates a full valid Page 1 data object */
const pageOneDataArb = fc.record({
  name: validNameArb,
  email: validEmailArb,
  phone: validPhoneArb,
  core_request: validCoreRequestArb,
})

// --- Helpers ---

function renderWithState(component: React.ReactElement, state: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/form', state }]}>
      {component}
    </MemoryRouter>
  )
}

describe('Property 3: Data retained across page navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedCreateSubmission.mockResolvedValue({
      submission_id: 'test-id-123',
      progress_state: 50,
      message: 'Created',
    })
  })

  it('NegativeForm includes all Page 1 fields unchanged in submission payload', async () => {
    await fc.assert(
      fc.asyncProperty(pageOneDataArb, async (pageOneData) => {
        vi.clearAllMocks()
        mockedCreateSubmission.mockResolvedValue({
          submission_id: 'test-id-123',
          progress_state: 50,
          message: 'Created',
        })

        const { unmount } = renderWithState(<NegativeForm />, pageOneData)

        // Fill required form-specific fields
        const categorySelect = screen.getByLabelText(/issue category/i)
        fireEvent.change(categorySelect, { target: { value: 'billing' } })

        const descriptionField = screen.getByLabelText(/detailed description/i)
        fireEvent.change(descriptionField, {
          target: { value: 'This is a valid description with enough characters' },
        })

        // Submit the form
        const submitButton = screen.getByRole('button', { name: /submit/i })
        fireEvent.click(submitButton)

        await waitFor(() => {
          expect(mockedCreateSubmission).toHaveBeenCalledTimes(1)
        })

        const payload: SubmissionCreatePayload = mockedCreateSubmission.mock.calls[0][0]

        // Assert Page 1 data is retained unchanged
        expect(payload.customer_name).toBe(pageOneData.name)
        expect(payload.email).toBe(pageOneData.email || null)
        expect(payload.phone).toBe(pageOneData.phone || null)
        expect(payload.core_request).toBe(pageOneData.core_request)

        unmount()
      }),
      { numRuns: 100 }
    )
  })

  it('PositiveForm includes all Page 1 fields unchanged in submission payload', async () => {
    await fc.assert(
      fc.asyncProperty(pageOneDataArb, async (pageOneData) => {
        vi.clearAllMocks()
        mockedCreateSubmission.mockResolvedValue({
          submission_id: 'test-id-123',
          progress_state: 100,
          message: 'Created',
        })

        const { unmount } = renderWithState(<PositiveForm />, pageOneData)

        // Fill required form-specific fields
        const praiseField = screen.getByLabelText(/your praise/i)
        fireEvent.change(praiseField, {
          target: { value: 'Great service!' },
        })

        // Submit the form
        const submitButton = screen.getByRole('button', { name: /submit/i })
        fireEvent.click(submitButton)

        await waitFor(() => {
          expect(mockedCreateSubmission).toHaveBeenCalledTimes(1)
        })

        const payload: SubmissionCreatePayload = mockedCreateSubmission.mock.calls[0][0]

        // Assert Page 1 data is retained unchanged
        expect(payload.customer_name).toBe(pageOneData.name)
        expect(payload.email).toBe(pageOneData.email || null)
        expect(payload.phone).toBe(pageOneData.phone || null)
        expect(payload.core_request).toBe(pageOneData.core_request)

        unmount()
      }),
      { numRuns: 100 }
    )
  })

  it('NeutralForm includes all Page 1 fields unchanged in submission payload', async () => {
    await fc.assert(
      fc.asyncProperty(pageOneDataArb, async (pageOneData) => {
        vi.clearAllMocks()
        mockedCreateSubmission.mockResolvedValue({
          submission_id: 'test-id-123',
          progress_state: 25,
          message: 'Created',
        })

        const { unmount } = renderWithState(<NeutralForm />, pageOneData)

        // Fill required form-specific fields
        const commentField = screen.getByLabelText(/your comment/i)
        fireEvent.change(commentField, {
          target: { value: 'This is a general comment.' },
        })

        // Submit the form
        const submitButton = screen.getByRole('button', { name: /submit/i })
        fireEvent.click(submitButton)

        await waitFor(() => {
          expect(mockedCreateSubmission).toHaveBeenCalledTimes(1)
        })

        const payload: SubmissionCreatePayload = mockedCreateSubmission.mock.calls[0][0]

        // Assert Page 1 data is retained unchanged
        expect(payload.customer_name).toBe(pageOneData.name)
        expect(payload.email).toBe(pageOneData.email || null)
        expect(payload.phone).toBe(pageOneData.phone || null)
        expect(payload.core_request).toBe(pageOneData.core_request)

        unmount()
      }),
      { numRuns: 100 }
    )
  })
})
