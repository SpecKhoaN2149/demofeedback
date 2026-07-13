import { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import styles from './SeverityBadge.module.css'

export interface SeverityBadgeProps {
  /** Severity on the 1–10 dashboard scale. */
  severity: number | null | undefined
  /** NLP rationale shown in the ⓘ tooltip. */
  reasoning?: string | null
}

/** Bucket a 1–10 severity into a color band. */
function severityClass(sev: number): string {
  if (sev >= 8) return styles.critical
  if (sev >= 6) return styles.high
  if (sev >= 4) return styles.medium
  return styles.low
}

/**
 * Displays severity as "N / 10" in a color-coded chip. When reasoning is
 * provided, an ⓘ affordance reveals the NLP's rationale on hover/focus.
 *
 * The tooltip is rendered in a portal with fixed positioning so it is never
 * clipped by a scrollable/overflow-hidden ancestor (e.g. the table wrapper).
 */
export default function SeverityBadge({ severity, reasoning }: SeverityBadgeProps) {
  const infoRef = useRef<HTMLSpanElement>(null)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)

  const show = useCallback(() => {
    const el = infoRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    // Anchor the tooltip just above the icon, horizontally centered on it.
    setCoords({ top: r.top - 8, left: r.left + r.width / 2 })
  }, [])

  const hide = useCallback(() => setCoords(null), [])

  if (severity == null) {
    return <span className={styles.empty}>—</span>
  }

  return (
    <span className={styles.wrapper}>
      <span className={`${styles.chip} ${severityClass(severity)}`}>
        {severity} <span className={styles.scale}>/ 10</span>
      </span>
      {reasoning ? (
        <span
          ref={infoRef}
          className={styles.info}
          tabIndex={0}
          aria-label={`Severity reasoning: ${reasoning}`}
          onMouseEnter={show}
          onMouseLeave={hide}
          onFocus={show}
          onBlur={hide}
        >
          <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true" focusable="false">
            <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="10" cy="6.2" r="1.05" fill="currentColor" />
            <rect x="9.1" y="8.6" width="1.8" height="6" rx="0.9" fill="currentColor" />
          </svg>
          {coords &&
            createPortal(
              <span
                role="tooltip"
                className={styles.tooltip}
                style={{ top: coords.top, left: coords.left }}
              >
                {reasoning}
              </span>,
              document.body
            )}
        </span>
      ) : null}
    </span>
  )
}
