import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import PositiveForm, { validatePositiveForm } from './PositiveForm'

const mockedNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
    useLocation: () => ({
      state: {
        name: 'John Doe',
        email: 'john@example.com',
        phone: '+1234567890',
        core_request: 'Great service',
      },
    }),
  }
})

vi.mock('../api/client', () => ({
  createSubmission: vi.fn(),
}))

import { createSubmission } from '../api/client'

const mockedCreateSubmission = vi.mocked(createSubmission)

function renderPositiveForm() {
  return render(
    <MemoryRouter>
      <PositiveForm />
    </MemoryRouter>
  )
}

describe('PositiveForm', () => {
  beforeEach(() => {
    mockedNavigate.mockClear()
    mockedCreateSubmission.mockClear()
  })

  it('renders praise textarea and social sharing toggle', () => {
    renderPositiveForm()
    expect(screen.getByLabelText('Your Praise')).toBeInTheDocument()
    expect(screen.getByLabelText(/allow social sharing/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
  })

  it('social sharing toggle defaults to off', () => {
    renderPositiveForm()
    const toggle = screen.getByLabelText(/allow social sharing/i) as HTMLInputElement
    expect(toggle.checked).toBe(false)
  })

  it('shows character counter', () => {
    renderPositiveForm()
    expect(screen.getByText('0/2000')).toBeInTheDocument()
  })

  it('updates character counter as user types', () => {
    renderPositiveForm()
    fireEvent.change(screen.getByLabelText('Your Praise'), { target: { value: 'Hello' } })
    expect(screen.getByText('5/2000')).toBeInTheDocument()
  })

  it('shows error when praise is empty', () => {
    renderPositiveForm()
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
    expect(screen.getByText('Praise is required.')).toBeInTheDocument()
    expect(mockedCreateSubmission).not.toHaveBeenCalled()
  })

  it('shows error when praise is only whitespace', () => {
    renderPositiveForm()
    fireEvent.change(screen.getByLabelText('Your Praise'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
    expect(screen.getByText('Praise is required.')).toBeInTheDocument()
    expect(mockedCreateSubmission).not.toHaveBeenCalled()
  })

  it('submits successfully and navigates to status page', async () => {
    mockedCreateSubmission.mockResolvedValue({
      submission_id: 'abc-123',
      progress_state: 100,
      message: 'Created',
    })

    renderPositiveForm()
    fireEvent.change(screen.getByLabelText('Your Praise'), {
      target: { value: 'Excellent service!' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => {
      expect(mockedNavigate).toHaveBeenCalledWith('/status/abc-123')
    })

    expect(mockedCreateSubmission).toHaveBeenCalledWith({
      customer_name: 'John Doe',
      email: 'john@example.com',
      phone: '+1234567890',
      core_request: 'Great service',
      sentiment: 'positive',
      praise_text: 'Excellent service!',
      social_sharing: false,
    })
  })

  it('sends social_sharing=true when toggle is enabled', async () => {
    mockedCreateSubmission.mockResolvedValue({
      submission_id: 'def-456',
      progress_state: 100,
      message: 'Created',
    })

    renderPositiveForm()
    fireEvent.change(screen.getByLabelText('Your Praise'), {
      target: { value: 'Great work!' },
    })
    fireEvent.click(screen.getByLabelText(/allow social sharing/i))
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => {
      expect(mockedCreateSubmission).toHaveBeenCalledWith(
        expect.objectContaining({ social_sharing: true })
      )
    })
  })

  it('shows warning on marketing failure but still navigates', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    mockedCreateSubmission.mockResolvedValue({
      submission_id: 'warn-789',
      progress_state: 100,
      message: 'Created',
      warning: 'Marketing logging is pending.',
    })

    renderPositiveForm()
    fireEvent.change(screen.getByLabelText('Your Praise'), {
      target: { value: 'Love it!' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('Marketing logging is pending.')
      expect(mockedNavigate).toHaveBeenCalledWith('/status/warn-789')
    })

    alertSpy.mockRestore()
  })

  it('displays error message on submission failure', async () => {
    mockedCreateSubmission.mockRejectedValue(new Error('Network error'))

    renderPositiveForm()
    fireEvent.change(screen.getByLabelText('Your Praise'), {
      target: { value: 'Good stuff!' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
    expect(mockedNavigate).not.toHaveBeenCalled()
  })
})

describe('validatePositiveForm', () => {
  it('returns no errors for valid praise', () => {
    const errors = validatePositiveForm('Great experience!')
    expect(errors).toEqual({})
  })

  it('rejects empty praise', () => {
    const errors = validatePositiveForm('')
    expect(errors.praise).toBe('Praise is required.')
  })

  it('rejects whitespace-only praise', () => {
    const errors = validatePositiveForm('   \t\n  ')
    expect(errors.praise).toBe('Praise is required.')
  })

  it('rejects praise longer than 2000 characters', () => {
    const errors = validatePositiveForm('a'.repeat(2001))
    expect(errors.praise).toBe('Praise must be 2000 characters or fewer.')
  })

  it('accepts praise exactly 2000 characters', () => {
    const errors = validatePositiveForm('a'.repeat(2000))
    expect(errors).toEqual({})
  })

  it('accepts praise of 1 character', () => {
    const errors = validatePositiveForm('x')
    expect(errors).toEqual({})
  })
})
