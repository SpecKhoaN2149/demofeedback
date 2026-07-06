import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

// Feature: spectrum-ui-redesign, Property 10: Interactive elements have visible focus indicator
//
// For any interactive component in the Component Library (Button, Input,
// Textarea, Select, interactive Card) — plus the interactive layout links
// (Header, Footer, AdminSidebar) and the global keyboard-focus baseline
// (reset.css) — when the component receives keyboard focus it SHALL render a
// visible focus indicator: either a solid outline or a box-shadow ring drawn
// with a Spectrum brand color (Spectrum Blue `--spectrum-color-primary`
// / rgba(0,89,184,…), or the Spectrum accent blue `--spectrum-color-accent`).
//
// jsdom does NOT compute CSS Module `:focus-visible` / `:focus` stylesheet
// rules into resolved styles, so a runtime `getComputedStyle` assertion cannot
// observe these indicators. We therefore take a STATIC-ANALYSIS approach: read
// each interactive component's stylesheet from disk and assert its focus rule
// block declares a branded, visible indicator.
//
// Validates: Requirements 13.3

const testDir = dirname(fileURLToPath(import.meta.url))

/** Enumerated list of stylesheets that back an interactive element. */
const INTERACTIVE_STYLESHEETS = [
  '../components/ui/Button/Button.module.css',
  '../components/ui/Card/Card.module.css',
  '../components/ui/Input/Input.module.css',
  '../components/ui/Textarea/Textarea.module.css',
  '../components/ui/Select/Select.module.css',
  '../components/layout/Header/Header.module.css',
  '../components/layout/Footer/Footer.module.css',
  '../components/layout/AdminSidebar/AdminSidebar.module.css',
  '../styles/reset.css',
] as const

/**
 * Extract every CSS rule block whose selector targets a focus state
 * (`:focus` or `:focus-visible`). Matches innermost `{ ... }` blocks, which is
 * sufficient here since no focus rule is nested inside another declaration.
 */
function extractFocusRuleBodies(css: string): string[] {
  const bodies: string[] = []
  const ruleRegex = /([^{}]+)\{([^{}]*)\}/g
  let match: RegExpExecArray | null
  while ((match = ruleRegex.exec(css)) !== null) {
    const selector = match[1].trim()
    const body = match[2].trim()
    if (selector.includes(':focus')) {
      bodies.push(body)
    }
  }
  return bodies
}

/**
 * A focus rule body counts as a branded, visible indicator if it declares
 * either:
 *   - a solid `outline` using a Spectrum brand color token, OR
 *   - a `box-shadow` ring drawn in Spectrum Blue (rgba(0, 89, 184, …)).
 */
function hasBrandedVisibleFocusIndicator(body: string): boolean {
  const hasBrandedOutline =
    /outline:\s*\d+px\s+solid\s+var\(--spectrum-color-(primary|accent)\)/.test(
      body
    )
  const hasSpectrumBlueGlow =
    /box-shadow:[^;]*rgba\(\s*0\s*,\s*89\s*,\s*184/.test(body)
  return hasBrandedOutline || hasSpectrumBlueGlow
}

describe('Interactive element focus indicators (property-based)', () => {
  it('every interactive stylesheet declares a branded, visible focus indicator', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...INTERACTIVE_STYLESHEETS),
        (relativePath) => {
          const css = readFileSync(resolve(testDir, relativePath), 'utf-8')
          const focusRuleBodies = extractFocusRuleBodies(css)

          // There must be at least one focus rule to indicate focus visibly.
          expect(
            focusRuleBodies.length,
            `${relativePath} declares no :focus / :focus-visible rule`
          ).toBeGreaterThan(0)

          // At least one focus rule must render a branded, visible indicator.
          const hasIndicator = focusRuleBodies.some(
            hasBrandedVisibleFocusIndicator
          )
          expect(
            hasIndicator,
            `${relativePath} has no branded visible focus indicator (solid outline or Spectrum Blue box-shadow)`
          ).toBe(true)
        }
      ),
      { numRuns: 200 }
    )
  })
})
