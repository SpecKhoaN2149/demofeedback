/**
 * Shared dark "command center" chart theme for the admin dashboard.
 *
 * Centralizes the neon-on-navy palette, axis/grid colors, and a custom Recharts
 * tooltip so every visual (bars, area, pie, map) reads as one cohesive techy
 * surface.
 */
import styles from './chartTheme.module.css'

/** Core light-theme chart colors (aligned with tokens.css). */
export const CHART = {
  grid: '#EAEFF5',
  axis: '#607086',
  axisLine: '#D5DEE8',
  primary: '#0059B8',
  cyan: '#00A3E0',
  teal: '#00B39A',
  green: '#2E7D32',
  amber: '#F5A623',
  orange: '#EF6C00',
  red: '#D32F2F',
  violet: '#7C5CE0',
  neutral: '#94A3B8',
} as const

/** Sentiment colors on a light background. */
export const SENTIMENT_COLOR: Record<string, string> = {
  negative: CHART.red,
  neutral: CHART.neutral,
  positive: CHART.green,
}

/** Per-source/platform colors. */
export const SOURCE_COLOR: Record<string, string> = {
  direct: CHART.primary,
  x: '#111827',
  reddit: '#FF4500',
  facebook: '#1877F2',
}

/** Color-band a 1-10 severity value. 1-3 green → 9-10 red. */
export function severityColor(sev: number | null): string {
  if (sev == null) return CHART.neutral
  if (sev >= 9) return CHART.red
  if (sev >= 7) return CHART.orange
  if (sev >= 4) return CHART.amber
  return CHART.green
}

interface TooltipEntry {
  dataKey?: string | number
  name?: string | number
  value?: string | number
  color?: string
  payload?: Record<string, unknown>
}

interface ChartTooltipProps {
  active?: boolean
  payload?: TooltipEntry[]
  label?: string | number
  /** Optional formatter for the tooltip title (the axis label). */
  labelFormatter?: (label: string | number) => string
  /** Optional suffix appended to each value (e.g. "/10"). */
  valueSuffix?: string
  /** Hide the series name row (useful for single-series charts). */
  hideName?: boolean
}

/**
 * Dark, rounded, glowing tooltip used across every dashboard chart.
 * Rendered via Recharts' `content` prop so styling is fully under our control.
 */
export function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
  valueSuffix = '',
  hideName = false,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null

  return (
    <div className={styles.tooltip}>
      {label != null && (
        <div className={styles.tooltipLabel}>
          {labelFormatter ? labelFormatter(label) : label}
        </div>
      )}
      {payload.map((entry, i) => (
        <div key={entry.dataKey ?? i} className={styles.tooltipRow}>
          <span className={styles.tooltipDot} style={{ background: entry.color }} />
          {!hideName && entry.name != null && (
            <span className={styles.tooltipName}>{entry.name}</span>
          )}
          <span className={styles.tooltipValue}>
            {entry.value}
            {valueSuffix}
          </span>
        </div>
      ))}
    </div>
  )
}
