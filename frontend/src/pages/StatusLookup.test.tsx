import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import StatusLookup from './StatusLookup'

const mockedNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
  }
})

function renderStatusLookup() {
  return render(
    <MemoryRouter>
      <StatusLookup />
    </MemoryRouter>
  )
}

describe('StatusLookup', () => {
  beforeEach(() => {
    mockedNavigate.mockClear()
  })

  it('renders the submission ID field and track button', () => {
    renderStatusLookup()
    expect(screen.getByLabelText('Submission ID')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Track Status' })).toBeInTheDocument()
  })

  it('shows an error and does not navigate when the ID is empty', () => {
    renderStatusLookup()
    fireEvent.click(screen.getByRole('button', { name: 'Track Status' }))
    expect(screen.getByText('Please enter your submission ID.')).toBeInTheDocument()
    expect(mockedNavigate).not.toHaveBeenCalled()
  })

  it('navigates to the status tracker with the trimmed, encoded ID', () => {
    renderStatusLookup()
    fireEvent.change(screen.getByLabelText('Submission ID'), {
      target: { value: '  abc-123  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Track Status' }))
    expect(mockedNavigate).toHaveBeenCalledWith('/status/abc-123')
  })
})
