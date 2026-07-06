import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SentimentSelect from './SentimentSelect'

const mockedNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockedNavigate,
  }
})

function renderSentimentSelect(state?: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/sentiment', state }]}>
      <SentimentSelect />
    </MemoryRouter>
  )
}

describe('SentimentSelect', () => {
  beforeEach(() => {
    mockedNavigate.mockClear()
  })

  it('renders within the navigation shell (header and footer present)', () => {
    renderSentimentSelect()
    // Footer copyright rendered by NavigationShell.
    expect(screen.getByText(/Charter Communications, Inc\./)).toBeInTheDocument()
    // Primary navigation from the header.
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
  })

  it('renders the three sentiment options as interactive cards', () => {
    renderSentimentSelect()
    expect(
      screen.getByRole('button', {
        name: 'I have a complaint: Report an issue for resolution',
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: 'I have praise: Share a compliment or kind word',
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: 'I have a general comment: Leave feedback or a suggestion',
      })
    ).toBeInTheDocument()
  })

  it('displays a title and description for each sentiment', () => {
    renderSentimentSelect()
    expect(screen.getByText('I have a complaint')).toBeInTheDocument()
    expect(screen.getByText('Report an issue for resolution')).toBeInTheDocument()
    expect(screen.getByText('I have praise')).toBeInTheDocument()
    expect(screen.getByText('I have a general comment')).toBeInTheDocument()
  })

  it('navigates to /negative on click, forwarding page-one state', () => {
    const state = { name: 'John', email: 'j@x.com', phone: '', core_request: 'Help' }
    renderSentimentSelect(state)
    fireEvent.click(
      screen.getByRole('button', {
        name: 'I have a complaint: Report an issue for resolution',
      })
    )
    expect(mockedNavigate).toHaveBeenCalledWith('/negative', { state })
  })

  it('navigates to /positive on click', () => {
    renderSentimentSelect()
    fireEvent.click(
      screen.getByRole('button', {
        name: 'I have praise: Share a compliment or kind word',
      })
    )
    expect(mockedNavigate).toHaveBeenCalledWith('/positive', { state: null })
  })

  it('navigates to /neutral on click', () => {
    renderSentimentSelect()
    fireEvent.click(
      screen.getByRole('button', {
        name: 'I have a general comment: Leave feedback or a suggestion',
      })
    )
    expect(mockedNavigate).toHaveBeenCalledWith('/neutral', { state: null })
  })

  it('navigates via keyboard activation (Enter)', () => {
    renderSentimentSelect()
    fireEvent.keyDown(
      screen.getByRole('button', {
        name: 'I have a complaint: Report an issue for resolution',
      }),
      { key: 'Enter' }
    )
    expect(mockedNavigate).toHaveBeenCalledWith('/negative', { state: null })
  })

  it('navigates via keyboard activation (Space)', () => {
    renderSentimentSelect()
    fireEvent.keyDown(
      screen.getByRole('button', {
        name: 'I have praise: Share a compliment or kind word',
      }),
      { key: ' ' }
    )
    expect(mockedNavigate).toHaveBeenCalledWith('/positive', { state: null })
  })
})
