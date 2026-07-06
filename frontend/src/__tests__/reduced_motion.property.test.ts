// Feature: spectrum-ui-redesign, Property 13: Reduced motion disables animations
/**
 * Property 13: Reduced motion disables animations
 *
 * For any animated element in the Frontend_App, when the
 * `prefers-reduced-motion: reduce` media query is active, the element SHALL
 * have all CSS transitions and animations disabled (transition-duration: 0ms
 * or animation: none).
 *
 * Approach: jsdom does not evaluate media queries against stylesheets, so this
 * is verified via STATIC ANALYSIS of `frontend/src/styles/animations.css`. We
 * assert that the file contains a `@media (prefers-reduced-motion: reduce)`
 * block that globally neutralizes animation and transition on the universal
 * selector with `!important`. fast-check iterates over the enumerated set of
 * rules/tokens that must be present inside that block.
 *
 * **Validates: Requirements 15.4**
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirnameLocal = dirname(fileURLToPath(import.meta.url))
const animationsCssPath = resolve(__dirnameLocal, '../styles/animations.css')
const css = readFileSync(animationsCssPath, 'utf-8')

/**
 * Extracts the body of the `@media (prefers-reduced-motion: reduce)` block by
 * balancing braces starting from the opening brace of the at-rule.
 */
function extractReducedMotionBlock(source: string): string {
  const mediaRegex = /@media[^{]*prefers-reduced-motion\s*:\s*reduce[^{]*\{/
  const match = mediaRegex.exec(source)
  if (!match) return ''

  const start = match.index + match[0].length
  let depth = 1
  let i = start
  for (; i < source.length && depth > 0; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') depth--
  }
  // i now points just past the closing brace of the @media block
  return source.slice(start, i - 1)
}

const reducedMotionBlock = extractReducedMotionBlock(css)

/**
 * Enumerated set of properties/rules that MUST be neutralized inside the
 * reduced-motion block. Each entry is a predicate against the block contents.
 */
interface NeutralizationRule {
  name: string
  test: (block: string) => boolean
}

// A near-zero duration such as 0, 0s, 0ms, 0.01ms, etc.
const NEAR_ZERO_DURATION = /(0(?:\.0*[1-9]\d*)?)\s*m?s|:\s*0\s*(?:!important|;|})/

const neutralizationRules: NeutralizationRule[] = [
  {
    name: 'universal selector present',
    test: (block) => /(^|[\s,{}])\*(?=[\s,{:])/.test(block),
  },
  {
    name: 'animation-duration neutralized with !important',
    test: (block) =>
      /animation-duration\s*:\s*[^;}]*!important/.test(block) &&
      /animation-duration\s*:\s*0(?:\.0*[1-9]\d*)?\s*m?s/.test(block),
  },
  {
    name: 'transition-duration neutralized with !important',
    test: (block) =>
      /transition-duration\s*:\s*[^;}]*!important/.test(block) &&
      /transition-duration\s*:\s*0(?:\.0*[1-9]\d*)?\s*m?s/.test(block),
  },
]

describe('Property 13: Reduced motion disables animations', () => {
  it('animations.css contains a prefers-reduced-motion: reduce media block', () => {
    expect(reducedMotionBlock.length).toBeGreaterThan(0)
  })

  it('every enumerated animation/transition property is neutralized inside the reduced-motion block', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: neutralizationRules.length - 1 }),
        (idx) => {
          const rule = neutralizationRules[idx]
          expect(
            rule.test(reducedMotionBlock),
            `Expected reduced-motion block to satisfy: ${rule.name}`
          ).toBe(true)
        }
      ),
      { numRuns: 200 }
    )
  })

  it('applies neutralization on the universal selector (global disable) for any enumerated duration token', () => {
    // The tokens that represent "disabled motion" durations we accept.
    const durationTokens = ['animation-duration', 'transition-duration']
    fc.assert(
      fc.property(fc.constantFrom(...durationTokens), (token) => {
        const declRegex = new RegExp(
          `${token}\\s*:\\s*0(?:\\.0*[1-9]\\d*)?\\s*m?s\\s*!important`
        )
        expect(
          declRegex.test(reducedMotionBlock),
          `Expected ${token} to be set to a ~0 duration with !important`
        ).toBe(true)
      }),
      { numRuns: 100 }
    )
  })

  it('near-zero duration pattern matches the block (sanity of the enumerated set)', () => {
    fc.assert(
      fc.property(fc.constant(reducedMotionBlock), (block) => {
        expect(NEAR_ZERO_DURATION.test(block)).toBe(true)
      }),
      { numRuns: 100 }
    )
  })
})
