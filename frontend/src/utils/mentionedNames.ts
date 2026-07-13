/**
 * Best-effort extraction of person names praised in feedback text, so staff can
 * give kudos. Conservative and cue-based to limit false positives: it looks for
 * a capitalized name that follows a praise/role cue (e.g. "thanks to Marcus",
 * "technician James", "shoutout to Priya").
 *
 * This is a lightweight heuristic, not full NER — it's meant to surface obvious
 * shoutouts, not to be exhaustive.
 */

// Words that look like names but usually aren't a person (places/brands the
// mock + real data commonly contain). Compared case-insensitively.
const STOPWORDS = new Set(
  [
    'spectrum', 'austin', 'denver', 'orlando', 'raleigh', 'charlotte', 'columbus',
    'cincinnati', 'tampa', 'manhattan', 'colorado', 'texas', 'florida', 'york',
    'los', 'angeles', 'san', 'antonio', 'louis', 'north', 'south', 'carolina',
    'ohio', 'missouri', 'california', 'the', 'wifi', 'wi', 'internet', 'support',
  ].map((w) => w.toLowerCase())
)

// A capitalized name token, optionally a two-part name (first + last).
const NAME = '[A-Z][a-z]{2,}(?:\\s+[A-Z][a-z]{2,})?'

// Cue → name. Roles ("technician James") or praise directs ("thanks to Marcus").
// Cue first-letters are case-flexible (mid-sentence or sentence-start), but the
// NAME part stays case-sensitive so we only capture Capitalized names — hence
// no global "i" flag (which would break the [A-Z] name detection).
const CUE_RE = new RegExp(
  `(?:[Tt]hank(?:s| you)?(?:\\s+to)?|[Ss]hout\\s?out(?:\\s+to)?|[Kk]udos(?:\\s+to)?|` +
    `[Pp]rops(?:\\s+to)?|[Nn]amed|[Aa]gent|[Tt]echnician|[Tt]ech|[Ii]nstaller|` +
    `[Ee]ngineer|[Ss]pecialist|[Rr]ep(?:resentative)?)\\s+` +
    `(?:to\\s+|named\\s+)?(${NAME})`,
  'g'
)

function isName(candidate: string): boolean {
  const parts = candidate.split(/\s+/)
  // Reject if every part is a stopword (place/brand), keep otherwise.
  return parts.some((p) => !STOPWORDS.has(p.toLowerCase()))
}

/** Return the unique list of praised person names mentioned in `text`. */
export function extractMentionedNames(text: string): string[] {
  if (!text) return []
  const found = new Map<string, string>() // lowercased key → original casing
  let m: RegExpExecArray | null
  CUE_RE.lastIndex = 0
  while ((m = CUE_RE.exec(text)) !== null) {
    const name = m[1].trim()
    if (isName(name)) {
      const key = name.toLowerCase()
      if (!found.has(key)) found.set(key, name)
    }
  }
  return Array.from(found.values())
}
