import React from 'react'

export interface SpectrumLogoProps {
  /**
   * Color treatment of the wordmark.
   * - `'light'` renders the wordmark in white (#FFFFFF) for use on dark backgrounds.
   * - `'dark'` renders the wordmark in Spectrum Blue (#0059B8) for use on light backgrounds.
   * @default 'dark'
   */
  variant?: 'light' | 'dark'
  /** Additional class name(s) merged onto the root SVG element. */
  className?: string
}

/** Fill color per variant. */
const VARIANT_FILL: Record<NonNullable<SpectrumLogoProps['variant']>, string> = {
  light: '#FFFFFF',
  dark: '#0059B8',
}

/**
 * Spectrum brand wordmark rendered as inline SVG.
 *
 * Branding rules enforced:
 * - `aria-label="Spectrum"` so the logo is announced correctly by screen readers.
 * - `variant` controls the fill color (white for dark surfaces, Spectrum Blue for light surfaces).
 * - Sizing constrained to a min-width of 120px and max-width of 160px while maintaining
 *   the wordmark's aspect ratio (via `preserveAspectRatio` and the intrinsic viewBox ratio).
 * - Clear space is preserved with padding equal to the height of the "S" glyph, so the
 *   wordmark is never crowded by adjacent elements.
 */
const SpectrumLogo: React.FC<SpectrumLogoProps> = ({
  variant = 'dark',
  className,
}) => {
  const fill = VARIANT_FILL[variant]

  // The viewBox is 200x40 (5:1 aspect ratio). The cap height of the "S" glyph is
  // ~32px which, scaled to the rendered width, defines the clear-space padding.
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 200 40"
      role="img"
      aria-label="Spectrum"
      className={className}
      preserveAspectRatio="xMidYMid meet"
      style={{
        display: 'block',
        width: '100%',
        minWidth: '120px',
        maxWidth: '160px',
        height: 'auto',
        // Clear space: padding equal to the height of the "S" glyph (0.8em of the 40px box).
        padding: '0.8em',
        boxSizing: 'content-box',
      }}
    >
      <text
        x="0"
        y="30"
        fontFamily="'Spectrum Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
        fontSize="32"
        fontWeight="700"
        letterSpacing="-0.5"
        fill={fill}
      >
        Spectrum
      </text>
    </svg>
  )
}

SpectrumLogo.displayName = 'SpectrumLogo'

export default SpectrumLogo
