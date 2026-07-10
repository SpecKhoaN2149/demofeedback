/**
 * Pure source/platform display helper for admin feedback views.
 *
 * Given a feedback row's source attribution, returns a small render model
 * `{ label, detail }` that the admin UI can display directly:
 *
 * - `social` → label "Social", detail is the originating platform. When the
 *   platform is missing/null, `detail` is an empty string — the caller renders
 *   nothing (no placeholder text, no error) (Requirement 6.2).
 * - `direct` → label "Direct", detail is the channel (e.g. "web_form").
 *   When the channel is missing/null, `detail` is an empty string
 *   (Requirement 6.3).
 *
 * This function is intentionally tiny, pure, and total: it never throws for
 * any input, including malformed or partial rows (Requirement 6.4). This makes
 * it safe to call directly in render paths and straightforward to
 * property-test.
 */
export interface SourceDisplayRow {
  source_type: 'direct' | 'social'
  platform?: 'reddit' | 'x' | 'facebook' | null
  channel?: string | null
}

export interface SourceDisplay {
  label: string
  detail: string
}

export function sourceDisplay(row: SourceDisplayRow): SourceDisplay {
  // Defensive read: never throw, even if `row` is null/undefined or partial.
  const source = row?.source_type

  if (source === 'social') {
    return { label: 'Social', detail: row?.platform ?? '' }
  }

  // Treat everything else (including 'direct') as direct-style display.
  return { label: 'Direct', detail: row?.channel ?? '' }
}
