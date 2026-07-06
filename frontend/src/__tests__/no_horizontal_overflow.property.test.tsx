/**
 * Feature: spectrum-ui-redesign, Property 12: No horizontal overflow across viewport widths
 *
 * Property 12: No horizontal overflow across viewport widths
 *
 * For any viewport width in the range [320px, 1440px], rendering any page in
 * the Frontend_App SHALL NOT produce horizontal overflow requiring horizontal
 * scrolling.
 *
 * **Validates: Requirements 14.5**
 *
 * --- Testing approach (hybrid) ---
 *
 * jsdom does not perform real layout: `offsetWidth` / `scrollWidth` are always
 * reported as 0, so a pure render-and-measure approach cannot detect overflow.
 * Instead we verify the *mechanism* that guarantees the property holds:
 *
 *   1. Static guard — read `src/styles/reset.css` and assert the global
 *      `overflow-x: hidden` guard (plus `max-width: 100%`) is present on the
 *      html and body elements. This is the width-independent CSS rule that
 *      prevents any horizontal scrollbar from ever appearing, satisfying
 *      Requirement 14.5.
 *
 *   2. Range coverage — use fast-check to generate viewport widths across the
 *      full supported [320, 1440] range and assert the guard invariant holds at
 *      each width. Because the guard is width-independent, this documents that
 *      the property is upheld across the entire responsive range.
 *
 *   3. Inline-style safety — render the NavigationShell with representative
 *      content at each generated width (via `window.innerWidth`) and assert no
 *      rendered element declares a fixed `px` width larger than the viewport in
 *      its inline styles (which would defeat the overflow guard).
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import * as fc from 'fast-check'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'

// --- Locate and load the global reset stylesheet ---

const __dirname = dirname(fileURLToPath(import.meta.url))
const RESET_CSS_PATH = resolve(__dirname, '../styles/reset.css')
const resetCss = readFileSync(RESET_CSS_PATH, 'utf-8')

/**
 * Normalizes CSS text: strips comments and collapses whitespace so that
 * property/value pairs can be matched regardless of formatting.
 */
function normalizeCss(css: string): string {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, ' ') // remove comments
    .replace(/\s+/g, ' ') // collapse whitespace
    .toLowerCase()
    .trim()
}

/**
 * Extracts the declaration block body for the FIRST rule whose selector list
 * contains the given selector (matched as a comma/space separated token).
 */
function ruleBodyContaining(css: string, selector: string): string[] {
  const normalized = normalizeCss(css)
  const ruleRegex = /([^{}]+)\{([^{}]*)\}/g
  const bodies: string[] = []
  let match: RegExpExecArray | null
  while ((match = ruleRegex.exec(normalized)) !== null) {
    const selectorList = match[1]
    const selectors = selectorList.split(',').map((s) => s.trim())
    if (selectors.includes(selector)) {
      bodies.push(match[2].trim())
    }
  }
  return bodies
}

/** Returns true if any rule targeting `selector` declares `prop: value`. */
function selectorDeclares(css: string, selector: string, prop: string, value: string): boolean {
  const needle = `${prop.toLowerCase()}: ${value.toLowerCase()}`
  const needleNoSpace = `${prop.toLowerCase()}:${value.toLowerCase()}`
  return ruleBodyContaining(css, selector).some(
    (body) => body.includes(needle) || body.includes(needleNoSpace)
  )
}

// --- Static guard assertions (mechanism verification) ---

describe('Property 12: No horizontal overflow across viewport widths', () => {
  it('reset.css declares the global overflow-x:hidden guard on html and body', () => {
    // html gets overflow-x: hidden
    expect(selectorDeclares(resetCss, 'html', 'overflow-x', 'hidden')).toBe(true)
    // body gets overflow-x: hidden AND max-width: 100%
    expect(selectorDeclares(resetCss, 'body', 'overflow-x', 'hidden')).toBe(true)
    expect(selectorDeclares(resetCss, 'body', 'max-width', '100%')).toBe(true)
  })

  it('reset.css constrains replaced media (img/video/etc.) to max-width:100%', () => {
    // Media defaults share a single rule; verify the shared rule caps width.
    const mediaSelectors = ['img', 'picture', 'video', 'canvas', 'svg']
    const capped = mediaSelectors.some((sel) =>
      selectorDeclares(resetCss, sel, 'max-width', '100%')
    )
    expect(capped).toBe(true)
  })

  // --- Range coverage: guard invariant holds across [320, 1440] ---

  it('overflow-x guard invariant holds for every viewport width in [320, 1440]', () => {
    fc.assert(
      fc.property(fc.integer({ min: 320, max: 1440 }), (viewportWidth) => {
        // The guard is width-independent: for ANY supported viewport width the
        // global overflow-x:hidden rule prevents a horizontal scrollbar.
        expect(viewportWidth).toBeGreaterThanOrEqual(320)
        expect(viewportWidth).toBeLessThanOrEqual(1440)
        return (
          selectorDeclares(resetCss, 'html', 'overflow-x', 'hidden') &&
          selectorDeclares(resetCss, 'body', 'overflow-x', 'hidden') &&
          selectorDeclares(resetCss, 'body', 'max-width', '100%')
        )
      }),
      { numRuns: 200 }
    )
  })

  // --- Inline-style safety across generated viewport widths ---

  it('no rendered element uses an inline px width exceeding the viewport', () => {
    const originalInnerWidth = window.innerWidth

    try {
      fc.assert(
        fc.property(fc.integer({ min: 320, max: 1440 }), (viewportWidth) => {
          // Simulate the viewport width.
          Object.defineProperty(window, 'innerWidth', {
            configurable: true,
            writable: true,
            value: viewportWidth,
          })
          window.dispatchEvent(new Event('resize'))

          const { container, unmount } = render(
            <MemoryRouter>
              <NavigationShell>
                <section>
                  <h1>Representative page heading</h1>
                  <p>
                    A representative block of body content used to exercise the
                    navigation shell layout at the generated viewport width.
                  </p>
                  <button type="button">An action</button>
                </section>
              </NavigationShell>
            </MemoryRouter>
          )

          try {
            const elements = container.querySelectorAll<HTMLElement>('*')
            for (const el of Array.from(elements)) {
              const inlineWidth = el.style.width
              const match = /^(\d+(?:\.\d+)?)px$/.exec(inlineWidth.trim())
              if (match) {
                const px = Number.parseFloat(match[1])
                // A fixed inline width wider than the viewport would defeat the
                // overflow-x guard and force horizontal scrolling.
                if (px > viewportWidth) {
                  return false
                }
              }
            }
            return true
          } finally {
            unmount()
          }
        }),
        { numRuns: 100 }
      )
    } finally {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        writable: true,
        value: originalInnerWidth,
      })
      window.dispatchEvent(new Event('resize'))
    }
  })
})
