import type { EnrichmentSummary } from '../../api/client'
import styles from './EnrichmentInsights.module.css'

export interface EnrichmentInsightsData {
  themes: Array<{ theme: string; confidence: number }>
  severity_score: number | null
  severity_factors?: string[]
  sentiment_confidence?: number | null
  language_code?: string | null
  language_confidence?: number | null
}

export interface EnrichmentInsightsProps {
  /** Enrichment data (from a submission's enrichment_result or queue summary). */
  data: EnrichmentInsightsData | EnrichmentSummary | null
  /** Compact mode renders a condensed view suited to table cells. */
  compact?: boolean
  /** Hide the legacy 1–5 severity block (when a 1–10 severity is shown elsewhere). */
  hideSeverity?: boolean
}

const MAX_SEVERITY = 5

function pct(value: number): string {
  return `${Math.round(value * 100)}%`
}

function severityDotClass(index: number, score: number): string {
  if (index >= score) return styles.dot
  if (score >= 4) return `${styles.dot} ${styles.dotSevere}`
  if (score === 3) return `${styles.dot} ${styles.dotElevated}`
  return `${styles.dot} ${styles.dotFilled}`
}

/**
 * Visualizes the NLP enrichment output for a single submission: detected
 * themes with confidence, a 1–5 severity meter with contributing factors,
 * the sentiment confidence, and the detected language.
 *
 * Renders nothing when there is no enrichment data.
 */
export default function EnrichmentInsights({
  data,
  compact = false,
  hideSeverity = false,
}: EnrichmentInsightsProps) {
  if (!data) return null

  const themes = data.themes ?? []
  const severity = data.severity_score
  const factors = data.severity_factors ?? []
  const sentimentConfidence = data.sentiment_confidence ?? null
  const languageCode = data.language_code ?? null
  const languageConfidence = data.language_confidence ?? null

  if (compact) {
    return (
      <div className={styles.compact}>
        {themes.length > 0 ? (
          <div className={styles.compactThemes}>
            {themes.map((t) => (
              <span key={t.theme} className={styles.compactChip}>
                {t.theme} {pct(t.confidence)}
              </span>
            ))}
          </div>
        ) : (
          <span className={styles.muted}>No themes</span>
        )}
        {severity != null && (
          <div className={styles.severityRow}>
            <span className={styles.severityDots} aria-hidden="true">
              {Array.from({ length: MAX_SEVERITY }, (_, i) => (
                <span key={i} className={severityDotClass(i, severity)} />
              ))}
            </span>
            <span className={styles.severityValue}>
              Severity {severity}/{MAX_SEVERITY}
            </span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.panel}>
      <div className={styles.section}>
        <p className={styles.label}>Detected themes</p>
        {themes.length > 0 ? (
          <div className={styles.themes}>
            {themes.map((t) => (
              <span key={t.theme} className={styles.themeChip}>
                {t.theme}
                <span className={styles.themeConfidence}>{pct(t.confidence)}</span>
              </span>
            ))}
          </div>
        ) : (
          <span className={styles.muted}>No themes detected.</span>
        )}
      </div>

      {!hideSeverity && severity != null && (
        <div className={styles.section}>
          <p className={styles.label}>Severity</p>
          <div className={styles.severityRow}>
            <span className={styles.severityDots} aria-hidden="true">
              {Array.from({ length: MAX_SEVERITY }, (_, i) => (
                <span key={i} className={severityDotClass(i, severity)} />
              ))}
            </span>
            <span className={styles.severityValue}>
              {severity} / {MAX_SEVERITY}
            </span>
          </div>
          {factors.length > 0 && (
            <ul className={styles.factors}>
              {factors.map((f, i) => (
                <li key={i} className={styles.factor}>
                  {f}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {sentimentConfidence != null && (
        <div className={styles.section}>
          <p className={styles.label}>Sentiment confidence</p>
          <div className={styles.confidenceRow}>
            <span className={styles.bar}>
              <span
                className={styles.barFill}
                style={{ width: pct(sentimentConfidence) }}
              />
            </span>
            <span className={styles.confidenceValue}>
              {pct(sentimentConfidence)}
            </span>
          </div>
        </div>
      )}

      {languageCode && (
        <div className={styles.section}>
          <p className={styles.label}>Detected language</p>
          <span className={styles.language}>
            {languageCode.toUpperCase()}
            {languageConfidence != null && ` · ${pct(languageConfidence)} confidence`}
          </span>
        </div>
      )}
    </div>
  )
}
