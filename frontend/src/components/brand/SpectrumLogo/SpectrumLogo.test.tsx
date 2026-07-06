import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import SpectrumLogo from './SpectrumLogo'

describe('SpectrumLogo', () => {
  it('renders an accessible wordmark with aria-label "Spectrum"', () => {
    render(<SpectrumLogo />)
    expect(screen.getByRole('img', { name: 'Spectrum' })).toBeInTheDocument()
  })

  it('renders the "Spectrum" wordmark text', () => {
    render(<SpectrumLogo />)
    expect(screen.getByText('Spectrum')).toBeInTheDocument()
  })

  it('uses Spectrum Blue (#0059B8) for the dark variant', () => {
    render(<SpectrumLogo variant="dark" />)
    expect(screen.getByText('Spectrum')).toHaveAttribute('fill', '#0059B8')
  })

  it('uses white (#FFFFFF) for the light variant', () => {
    render(<SpectrumLogo variant="light" />)
    expect(screen.getByText('Spectrum')).toHaveAttribute('fill', '#FFFFFF')
  })

  it('defaults to the dark (Spectrum Blue) variant', () => {
    render(<SpectrumLogo />)
    expect(screen.getByText('Spectrum')).toHaveAttribute('fill', '#0059B8')
  })

  it('enforces min-width 120px and max-width 160px while maintaining aspect ratio', () => {
    render(<SpectrumLogo />)
    const svg = screen.getByRole('img', { name: 'Spectrum' })
    expect(svg.style.minWidth).toBe('120px')
    expect(svg.style.maxWidth).toBe('160px')
    expect(svg).toHaveAttribute('viewBox', '0 0 200 40')
    expect(svg).toHaveAttribute('preserveAspectRatio', 'xMidYMid meet')
  })

  it('applies clear-space padding around the wordmark', () => {
    render(<SpectrumLogo />)
    const svg = screen.getByRole('img', { name: 'Spectrum' })
    expect(svg.style.padding).toBe('0.8em')
  })

  it('merges a custom className', () => {
    render(<SpectrumLogo className="header-logo" />)
    expect(screen.getByRole('img', { name: 'Spectrum' })).toHaveClass('header-logo')
  })
})
