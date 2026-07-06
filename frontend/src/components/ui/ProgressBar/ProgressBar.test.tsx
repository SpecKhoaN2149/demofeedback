import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ProgressBar from './ProgressBar'

describe('ProgressBar', () => {
  it('renders with progressbar role and ARIA attributes', () => {
    render(<ProgressBar value={40} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveAttribute('aria-valuenow', '40')
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })

  it('sets fill width to the current value percentage', () => {
    render(<ProgressBar value={65} />)
    const bar = screen.getByRole('progressbar')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill).toHaveStyle({ width: '65%' })
  })

  it('clamps values above 100 to 100', () => {
    render(<ProgressBar value={150} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '100')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill).toHaveStyle({ width: '100%' })
  })

  it('clamps negative values to 0', () => {
    render(<ProgressBar value={-25} />)
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '0')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill).toHaveStyle({ width: '0%' })
  })

  it('applies the complete style at 100%', () => {
    render(<ProgressBar value={100} />)
    const bar = screen.getByRole('progressbar')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill.className).toMatch(/complete/)
  })

  it('does not apply the complete style below 100%', () => {
    render(<ProgressBar value={99} />)
    const bar = screen.getByRole('progressbar')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill.className).not.toMatch(/complete/)
  })

  it('applies pulsing style when pulsing is true', () => {
    render(<ProgressBar value={50} pulsing />)
    const bar = screen.getByRole('progressbar')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill.className).toMatch(/pulsing/)
  })

  it('does not apply pulsing style by default', () => {
    render(<ProgressBar value={50} />)
    const bar = screen.getByRole('progressbar')
    const fill = bar.firstElementChild as HTMLElement
    expect(fill.className).not.toMatch(/pulsing/)
  })

  it('renders a label when provided', () => {
    render(<ProgressBar value={30} label="Processing" />)
    expect(screen.getByText('Processing')).toBeInTheDocument()
  })

  it('applies size variant classes', () => {
    const { rerender } = render(<ProgressBar value={10} size="small" />)
    let bar = screen.getByRole('progressbar')
    expect(bar.className).toMatch(/small/)

    rerender(<ProgressBar value={10} size="large" />)
    bar = screen.getByRole('progressbar')
    expect(bar.className).toMatch(/large/)

    rerender(<ProgressBar value={10} />)
    bar = screen.getByRole('progressbar')
    expect(bar.className).toMatch(/default/)
  })
})
