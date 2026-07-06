import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

// Feature: spectrum-ui-redesign, Property 9: Color contrast compliance
//
// For any foreground-background color pairing defined in the Design_Token
// system that is used for text rendering, the computed contrast ratio SHALL be
// at least 4.5:1 for normal text and at least 3:1 for large text, satisfying
// WCAG 2.1 Level AA.
//
// This test enumerates the REAL text foreground/background pairings that the
// design uses (derived from tokens.css and the Alert/Badge/Button/page usages)
// and samples across them with fast-check, asserting each meets its WCAG AA
// threshold. Thresholds are assigned from the actual rendered role of the text:
//   - normal text  (< 18px, or < 14px bold)      => 4.5:1
//   - large text   (>= 18px, or >= 14px bold)    => 3:1
//
// Validates: Requirements 13.1, 13.2

// ---------------------------------------------------------------------------
// WCAG relative-luminance + contrast-ratio implementation
// (per https://www.w3.org/TR/WCAG21/#dfn-relative-luminance and #dfn-contrast-ratio)
// ---------------------------------------------------------------------------

interface Rgb {
  r: number
  g: number
  b: number
}

/** Parse a 6-digit hex color (with or without leading #) into 0–255 channels. */
function hexToRgb(hex: string): Rgb {
  const normalized = hex.replace(/^#/, '')
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    throw new Error(`Invalid hex color: ${hex}`)
  }
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  }
}

/** Linearize a single sRGB channel (0–255) per the WCAG formula. */
function linearizeChannel(channel8bit: number): number {
  const c = channel8bit / 255
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

/** Compute WCAG relative luminance for an sRGB color. */
function relativeLuminance({ r, g, b }: Rgb): number {
  return (
    0.2126 * linearizeChannel(r) +
    0.7152 * linearizeChannel(g) +
    0.0722 * linearizeChannel(b)
  )
}

/** Compute the WCAG contrast ratio between two colors (>= 1). */
function contrastRatio(hexA: string, hexB: string): number {
  const lumA = relativeLuminance(hexToRgb(hexA))
  const lumB = relativeLuminance(hexToRgb(hexB))
  const lighter = Math.max(lumA, lumB)
  const darker = Math.min(lumA, lumB)
  return (lighter + 0.05) / (darker + 0.05)
}

// ---------------------------------------------------------------------------
// Real text pairings used in the design (values mirror tokens.css)
// ---------------------------------------------------------------------------

type TextSize = 'normal' | 'large'

interface Pairing {
  name: string
  fg: string
  bg: string
  /** Rendered text size class per WCAG (drives the required threshold). */
  size: TextSize
  /** Where this pairing actually appears in the UI. */
  usage: string
}

// Token values (source of truth: frontend/src/styles/tokens.css)
const TOKEN = {
  primary: '#0059B8',
  secondary: '#002F6C',
  white: '#FFFFFF',
  surface: '#F5F7FA',
  neutral200: '#E8ECF0',
  neutral700: '#212B36',
  success: '#2E7D32',
  warning: '#F57C00',
  error: '#D32F2F',
  info: '#0059B8',
  successLight: '#E8F5E9',
  warningLight: '#FFF3E0',
  errorLight: '#FDE8E8',
  infoLight: '#E3F2FD',
  // Dedicated "on-light" text tokens used by Badge (12px/600 => normal text).
  // Darkened where needed to meet WCAG AA 4.5:1 on the light tints.
  successText: '#2E7D32',
  warningText: '#8A4B00',
  errorText: '#B3261E',
  infoText: '#0059B8',
  textPrimary: '#1A1A1A',
  textSecondary: '#4A4A4A',
  textInverse: '#FFFFFF',
} as const

const PAIRINGS: Pairing[] = [
  // --- Body text on light surfaces (normal text => 4.5:1) ---
  {
    name: 'text-primary on white',
    fg: TOKEN.textPrimary,
    bg: TOKEN.white,
    size: 'normal',
    usage: 'Body/heading text on page + card backgrounds',
  },
  {
    name: 'text-primary on surface',
    fg: TOKEN.textPrimary,
    bg: TOKEN.surface,
    size: 'normal',
    usage: 'Body text on surface-tinted areas',
  },
  {
    name: 'text-secondary on white',
    fg: TOKEN.textSecondary,
    bg: TOKEN.white,
    size: 'normal',
    usage: 'Subtitles / helper text / stat labels',
  },
  {
    name: 'text-secondary on surface',
    fg: TOKEN.textSecondary,
    bg: TOKEN.surface,
    size: 'normal',
    usage: 'Secondary text on surface areas',
  },

  // --- Inverse text on brand fills (button labels, header) ---
  {
    name: 'text-inverse on primary',
    fg: TOKEN.textInverse,
    bg: TOKEN.primary,
    size: 'normal',
    usage: 'Primary button label (16px), active sidebar link',
  },
  {
    name: 'text-inverse on secondary',
    fg: TOKEN.textInverse,
    bg: TOKEN.secondary,
    size: 'normal',
    usage: 'Secondary button label, header (Dark Navy) text/logo',
  },

  // --- Alert body text: text-primary on the light severity tints ---
  {
    name: 'text-primary on success-light',
    fg: TOKEN.textPrimary,
    bg: TOKEN.successLight,
    size: 'normal',
    usage: 'Alert(success) body text (14px)',
  },
  {
    name: 'text-primary on warning-light',
    fg: TOKEN.textPrimary,
    bg: TOKEN.warningLight,
    size: 'normal',
    usage: 'Alert(warning) body text (14px)',
  },
  {
    name: 'text-primary on error-light',
    fg: TOKEN.textPrimary,
    bg: TOKEN.errorLight,
    size: 'normal',
    usage: 'Alert(error) body text (14px)',
  },
  {
    name: 'text-primary on info-light',
    fg: TOKEN.textPrimary,
    bg: TOKEN.infoLight,
    size: 'normal',
    usage: 'Alert(info) body text (14px)',
  },

  // --- Badge text: semantic color ON its light variant ---
  // Badges render at font-size xs (12px) / weight 600. Per WCAG, 12px bold is
  // NOT "large text" (that requires >= 14px bold), so these are normal text
  // and require 4.5:1.
  {
    name: 'success-text on success-light (Badge)',
    fg: TOKEN.successText,
    bg: TOKEN.successLight,
    size: 'normal',
    usage: 'Badge color="success" text (12px/600)',
  },
  {
    name: 'warning-text on warning-light (Badge)',
    fg: TOKEN.warningText,
    bg: TOKEN.warningLight,
    size: 'normal',
    usage: 'Badge color="warning" text (12px/600)',
  },
  {
    name: 'error-text on error-light (Badge)',
    fg: TOKEN.errorText,
    bg: TOKEN.errorLight,
    size: 'normal',
    usage: 'Badge color="error" text (12px/600)',
  },
  {
    name: 'info-text on info-light (Badge)',
    fg: TOKEN.infoText,
    bg: TOKEN.infoLight,
    size: 'normal',
    usage: 'Badge color="info" text (12px/600)',
  },
  {
    name: 'neutral-700 on neutral-200 (Badge)',
    fg: TOKEN.neutral700,
    bg: TOKEN.neutral200,
    size: 'normal',
    usage: 'Badge color="neutral" text (12px/600)',
  },
]

function requiredThreshold(size: TextSize): number {
  return size === 'large' ? 3 : 4.5
}

describe('Color contrast compliance (Property 9)', () => {
  // Sanity checks for the WCAG helpers against reference values.
  it('computes reference contrast ratios correctly', () => {
    // Black on white is the maximum contrast ratio: 21:1.
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 1)
    // Identical colors have the minimum ratio: 1:1.
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5)
    // Contrast is symmetric.
    expect(contrastRatio('#0059B8', '#FFFFFF')).toBeCloseTo(
      contrastRatio('#FFFFFF', '#0059B8'),
      10
    )
  })

  it('every defined text pairing meets its WCAG AA threshold', () => {
    fc.assert(
      fc.property(fc.constantFrom(...PAIRINGS), (pairing) => {
        const ratio = contrastRatio(pairing.fg, pairing.bg)
        const threshold = requiredThreshold(pairing.size)

        // Assert with a descriptive message so a failure names the pairing,
        // its measured ratio, and where it is used in the UI.
        expect(
          ratio,
          `Pairing "${pairing.name}" (${pairing.usage}) has contrast ` +
            `${ratio.toFixed(2)}:1 but requires >= ${threshold}:1 for ` +
            `${pairing.size} text`
        ).toBeGreaterThanOrEqual(threshold)
      }),
      { numRuns: 200 }
    )
  })
})
