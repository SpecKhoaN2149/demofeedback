import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LandingPage, { validateLandingForm } from './LandingPage'

const mockedNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
  }
})

function renderLandingPage() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  )
}

describe('LandingPage', () => {
  beforeEach(() => {
    mockedNavigate.mockClear()
  })

  it('renders all form fields', () => {
    renderLandingPage()
    expect(screen.getByLabelText('Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Phone')).toBeInTheDocument()
    expect(screen.getByLabelText('Core Request')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument()
  })

  it('shows error when name is empty', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'test@example.com' } })
    fireEvent.change(screen.getByLabelText('Core Request'), { target: { value: 'My request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('Name is required.')).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()
  })

  it('shows error when neither email nor phone is provided', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John' } })
    fireEvent.change(screen.getByLabelText('Core Request'), { target: { value: 'My request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('At least one of email or phone is required.')).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()
  })

  it('shows error for invalid email format', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'invalid-email' } })
    fireEvent.change(screen.getByLabelText('Core Request'), { target: { value: 'My request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('Email must match the format local@domain.tld.')).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()
  })

  it('shows error for invalid phone format', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '123' } })
    fireEvent.change(screen.getByLabelText('Core Request'), { target: { value: 'My request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(
      screen.getByText('Phone must be 7–15 digits, optionally prefixed with +.')
    ).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()
  })

  it('shows error when core request is empty', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'test@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('Core request is required.')).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()
  })

  it('preserves field values on validation failure', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'bad' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '555' } })
    fireEvent.change(screen.getByLabelText('Core Request'), { target: { value: 'Help me' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(screen.getByLabelText('Name')).toHaveValue('John')
    expect(screen.getByLabelText('Email')).toHaveValue('bad')
    expect(screen.getByLabelText('Phone')).toHaveValue('555')
    expect(screen.getByLabelText('Core Request')).toHaveValue('Help me')
  })

  it('navigates to /sentiment with form data on successful validation', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John Doe' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'john@example.com' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '+1234567890' } })
    fireEvent.change(screen.getByLabelText('Core Request'), {
      target: { value: 'I need help with billing' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(mockedNavigate).toHaveBeenCalledWith('/sentiment', {
      state: {
        name: 'John Doe',
        email: 'john@example.com',
        phone: '+1234567890',
        core_request: 'I need help with billing',
      },
    })
  })

  it('accepts valid submission with only phone (no email)', () => {
    renderLandingPage()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Jane' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '1234567' } })
    fireEvent.change(screen.getByLabelText('Core Request'), {
      target: { value: 'A question' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(mockedNavigate).toHaveBeenCalledWith('/sentiment', {
      state: {
        name: 'Jane',
        email: '',
        phone: '1234567',
        core_request: 'A question',
      },
    })
  })
})

describe('validateLandingForm', () => {
  it('returns no errors for valid data', () => {
    const errors = validateLandingForm({
      name: 'Alice',
      email: 'alice@test.com',
      phone: '',
      core_request: 'Hello',
    })
    expect(errors).toEqual({})
  })

  it('rejects whitespace-only name', () => {
    const errors = validateLandingForm({
      name: '   ',
      email: 'a@b.com',
      phone: '',
      core_request: 'x',
    })
    expect(errors.name).toBeDefined()
  })

  it('rejects name longer than 100 chars', () => {
    const errors = validateLandingForm({
      name: 'a'.repeat(101),
      email: 'a@b.com',
      phone: '',
      core_request: 'x',
    })
    expect(errors.name).toBeDefined()
  })

  it('accepts phone with + prefix', () => {
    const errors = validateLandingForm({
      name: 'Bob',
      email: '',
      phone: '+1234567890',
      core_request: 'test',
    })
    expect(errors.phone).toBeUndefined()
    expect(errors.contact).toBeUndefined()
  })

  it('rejects phone with letters', () => {
    const errors = validateLandingForm({
      name: 'Bob',
      email: '',
      phone: '123abc456',
      core_request: 'test',
    })
    expect(errors.phone).toBeDefined()
  })
})
