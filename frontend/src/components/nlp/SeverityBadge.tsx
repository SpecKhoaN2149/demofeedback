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
 */
export default function SeverityBadge({ severity, reasoning }: SeverityBadgeProps) {
  if (severity == null) {
    return <span className={styles.empty}>—</span>
  }

  return (
    <span className={styles.wrapper}>
      <span className={`${styles.chip} ${severityClass(severity)}`}>
        {severity} <span className={styles.scale}>/ 10</span>
      </span>
      {reasoning ? (
        <span className={styles.info} tabIndex={0} aria-label={`Severity reasoning: ${reasoning}`}>
          <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true" focusable="false">
            <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="10" cy="6.2" r="1.05" fill="currentColor" />
            <rect x="9.1" y="8.6" width="1.8" height="6" rx="0.9" fill="currentColor" />
          </svg>
          <span role="tooltip" className={styles.tooltip}>
            {reasoning}
          </span>
        </span>
      ) : null}
    </span>
  )
}
