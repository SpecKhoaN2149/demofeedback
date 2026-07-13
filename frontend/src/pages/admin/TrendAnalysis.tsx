import { useState, useEffect, type FormEvent } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useAuth } from '../../context/AuthContext'
import { runTrends, ApiError, type TrendRequest, type TrendReport } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import { CHART, ChartTooltip, SENTIMENT_COLOR } from '../../components/charts/chartTheme'
import styles from './admin.module.css'

const DAY_MS = 86_400_000

/** Format a Date to a `datetime-local`-compatible string in local time. */
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`
}

/** Short human date from a datetime-local string (e.g. "Jul 8"). */
function fmtDate(s: string): string {
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Prettify a short date for the sparkline axis/tooltip. */
function shortDay(iso: string): string {
  const parts = iso.split('-')
  if (parts.length !== 3) return iso
  return `${Number(parts[1])}/${Number(parts[2])}`
}

/**
 * Derive a single at-a-glance headline from the report, picking the most
 * notable shift. Returns the sentence plus a tone for coloring.
 */
function buildHeadline(report: TrendReport): { text: string; tone: 'bad' | 'good' | 'neutral' } {
  const base = report.baseline
  const cur = report.current
  const baseCount = base?.count ?? 0
  const curCount = cur?.count ?? 0

  // Biggest theme jump.
  let topTheme: { theme: string; baseline: number; current: number; jump: number } | null = null
  for (const s of report.theme_spikes) {
    const jump = s.current - s.baseline
    if (!topTheme || jump > topTheme.jump) topTheme = { ...s, jump }
  }

  // Negative sentiment share shift (in percentage points).
  const negBase = base?.sentiment_counts?.negative ?? 0
  const negCur = cur?.sentiment_counts?.negative ?? 0
  const negBasePct = baseCount ? (negBase / baseCount) * 100 : 0
  const negCurPct = curCount ? (negCur / curCount) * 100 : 0
  const negDelta = Math.round(negCurPct - negBasePct)

  // Volume % change.
  const volPct = baseCount ? Math.round(((curCount - baseCount) / baseCount) * 100) : curCount ? 100 : 0

  if (topTheme && topTheme.jump >= 2 && topTheme.current >= topTheme.baseline * 1.5) {
    const pct = topTheme.baseline
      ? Math.round(((topTheme.current - topTheme.baseline) / topTheme.baseline) * 100)
      : 100
    return {
      text: `“${topTheme.theme}” reports jumped ${pct}% (${topTheme.baseline} → ${topTheme.current}) vs the previous period.`,
      tone: 'bad',
    }
  }
  if (Math.abs(negDelta) >= 5) {
    return {
      text: `Negative sentiment ${negDelta > 0 ? 'up' : 'down'} ${Math.abs(negDelta)} pts vs the previous period (${Math.round(negBasePct)}% → ${Math.round(negCurPct)}%).`,
      tone: negDelta > 0 ? 'bad' : 'good',
    }
  }
  if (Math.abs(volPct) >= 10) {
    return {
      text: `Feedback volume ${volPct > 0 ? 'up' : 'down'} ${Math.abs(volPct)}% vs the previous period (${baseCount} → ${curCount}).`,
      tone: volPct > 0 ? 'bad' : 'good',
    }
  }
  return { text: 'No major shifts vs the previous period — things look steady.', tone: 'neutral' }
}

/** A KPI card showing baseline → current with a colored delta chip. */
function TrendKpi({
  label,
  baseline,
  current,
  delta,
  deltaSuffix = '',
  higherIsWorse = true,
}: {
  label: string
  baseline: string
  current: string
  delta: number
  deltaSuffix?: string
  /** When true, a positive delta is "bad" (red); when false, positive is "good". */
  higherIsWorse?: boolean
}) {
  const up = delta > 0
  const flat = delta === 0
  const bad = higherIsWorse ? up : delta < 0
  const cls = flat ? styles.deltaFlat : bad ? styles.deltaBad : styles.deltaGood
  const arrow = flat ? '→' : up ? '▲' : '▼'
  return (
    <div className={styles.trendKpi}>
      <div className={styles.trendKpiLabel}>{label}</div>
      <div className={styles.trendKpiValue}>
        <span className={styles.trendKpiBaseline}>{baseline}</span>
        <span className={styles.trendKpiArrow}>→</span>
        <span>{current}</span>
      </div>
      <div className={`${styles.trendKpiDelta} ${cls}`}>
        {arrow} {flat ? 'no change' : `${up ? '+' : ''}${delta}${deltaSuffix}`}
      </div>
    </div>
  )
}

/** Charts + KPI summary derived from a TrendReport. */
function TrendVisuals({ report }: { report: TrendReport }) {
  const base = report.baseline
  const cur = report.current
  const baseCount = base?.count ?? 0
  const curCount = cur?.count ?? 0
  const volDelta = curCount - baseCount
  const volPct =
    baseCount > 0 ? Math.round((volDelta / baseCount) * 100) : curCount > 0 ? 100 : 0

  // Window average severity is on the NLP 1-5 scale; show it on the 1-10 scale
  // used everywhere else in the app.
  const baseSev = (base?.average_severity ?? 0) * 2
  const curSev = (cur?.average_severity ?? 0) * 2
  const sevDelta = Math.round((curSev - baseSev) * 10) / 10

  const negBase = base?.sentiment_counts?.negative ?? 0
  const negCur = cur?.sentiment_counts?.negative ?? 0
  const negBasePct = baseCount ? Math.round((negBase / baseCount) * 100) : 0
  const negCurPct = curCount ? Math.round((negCur / curCount) * 100) : 0

  const themeData = report.theme_spikes.map((s) => ({
    theme: s.theme,
    baseline: s.baseline,
    current: s.current,
  }))
  const sentimentData = report.sentiment_shifts.map((s) => ({
    sentiment: s.sentiment,
    baseline: Math.round(s.baseline_ratio * 1000) / 10,
    current: Math.round(s.current_ratio * 1000) / 10,
  }))

  // Per-department breakdown: merge baseline + current department counts.
  const deptKeys = Array.from(
    new Set([
      ...Object.keys(base?.department_counts ?? {}),
      ...Object.keys(cur?.department_counts ?? {}),
    ])
  )
  const deptData = deptKeys
    .map((d) => ({
      department: d,
      baseline: base?.department_counts?.[d] ?? 0,
      current: cur?.department_counts?.[d] ?? 0,
    }))
    .sort((a, b) => b.current - a.current)

  // Daily volume series for the sparkline; mark where current window begins.
  const daily = (report.daily ?? []).map((d) => ({ ...d, label: shortDay(d.date) }))
  const boundaryLabel = daily.find((d) => d.current > 0)?.label

  const headline = buildHeadline(report)

  return (
    <>
      <div
        className={`${styles.trendHeadline} ${
          headline.tone === 'bad'
            ? styles.headlineBad
            : headline.tone === 'good'
              ? styles.headlineGood
              : styles.headlineNeutral
        }`}
        role="status"
      >
        <span className={styles.trendHeadlineIcon} aria-hidden="true">
          {headline.tone === 'bad' ? '⚠️' : headline.tone === 'good' ? '✅' : 'ℹ️'}
        </span>
        {headline.text}
      </div>

      {daily.length > 0 && (
        <div className={styles.trendSparkCard}>
          <div className={styles.trendSparkHead}>
            <h3 className={styles.trendChartTitle}>Daily volume</h3>
            <span className={styles.trendSparkTotal}>
              {daily.reduce((s, d) => s + d.total, 0)} total across window
            </span>
          </div>
          <ResponsiveContainer width="100%" height={90}>
            <AreaChart data={daily} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <defs>
                <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={CHART.primary} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={CHART.primary} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: CHART.axis }} axisLine={false} tickLine={false} minTickGap={24} />
              <Tooltip content={<ChartTooltip />} />
              {boundaryLabel && (
                <ReferenceLine x={boundaryLabel} stroke={CHART.axisLine} strokeDasharray="3 3" label={{ value: 'current', fontSize: 10, fill: CHART.axis, position: 'insideTopRight' }} />
              )}
              <Area type="monotone" dataKey="total" name="Feedback" stroke={CHART.primary} strokeWidth={2} fill="url(#sparkFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className={styles.trendKpis}>
        <TrendKpi
          label="Feedback volume"
          baseline={String(baseCount)}
          current={String(curCount)}
          delta={volPct}
          deltaSuffix="%"
          higherIsWorse
        />
        <TrendKpi
          label="Avg severity (1–10)"
          baseline={baseSev ? baseSev.toFixed(1) : '—'}
          current={curSev ? curSev.toFixed(1) : '—'}
          delta={sevDelta}
          higherIsWorse
        />
        <TrendKpi
          label="Negative share"
          baseline={`${negBasePct}%`}
          current={`${negCurPct}%`}
          delta={negCurPct - negBasePct}
          deltaSuffix="pts"
          higherIsWorse
        />
        <div className={styles.trendKpi}>
          <div className={styles.trendKpiLabel}>Themes rising</div>
          <div className={styles.trendKpiValue}>{report.theme_spikes.length}</div>
          <div className={`${styles.trendKpiDelta} ${styles.deltaFlat}`}>
            vs. baseline window
          </div>
        </div>
      </div>

      <div className={styles.trendCharts}>
        <div className={styles.trendChartCard}>
          <h3 className={styles.trendChartTitle}>Theme volume: baseline vs current</h3>
          {themeData.length === 0 ? (
            <p className={styles.nlpEmpty}>No rising themes in this window.</p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(220, themeData.length * 44)}>
              <BarChart data={themeData} layout="vertical" margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: CHART.axis }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="theme" width={130} tick={{ fontSize: 12, fill: '#334155' }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: 'rgba(0,89,184,0.06)' }} content={<ChartTooltip />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="baseline" name="Baseline" fill={CHART.neutral} radius={[0, 4, 4, 0]} barSize={11} />
                <Bar dataKey="current" name="Current" fill={CHART.primary} radius={[0, 4, 4, 0]} barSize={11} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className={styles.trendChartCard}>
          <h3 className={styles.trendChartTitle}>Sentiment mix (% of window)</h3>
          {sentimentData.length === 0 ? (
            <p className={styles.nlpEmpty}>No sentiment data in this window.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={sentimentData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="sentiment" tick={{ fontSize: 12, fill: CHART.axis }} axisLine={{ stroke: CHART.axisLine }} tickLine={false} />
                <YAxis unit="%" tick={{ fontSize: 12, fill: CHART.axis }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: 'rgba(0,89,184,0.06)' }} content={<ChartTooltip valueSuffix="%" />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="baseline" name="Baseline" radius={[4, 4, 0, 0]} barSize={22}>
                  {sentimentData.map((d) => (
                    <Cell key={`b-${d.sentiment}`} fill={SENTIMENT_COLOR[d.sentiment] ?? CHART.neutral} fillOpacity={0.4} />
                  ))}
                </Bar>
                <Bar dataKey="current" name="Current" radius={[4, 4, 0, 0]} barSize={22}>
                  {sentimentData.map((d) => (
                    <Cell key={`c-${d.sentiment}`} fill={SENTIMENT_COLOR[d.sentiment] ?? CHART.primary} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className={styles.trendChartCard}>
          <h3 className={styles.trendChartTitle}>By department: baseline vs current</h3>
          {deptData.length === 0 ? (
            <p className={styles.nlpEmpty}>No department data in this window.</p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(220, deptData.length * 44)}>
              <BarChart data={deptData} layout="vertical" margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: CHART.axis }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="department" width={140} tick={{ fontSize: 12, fill: '#334155' }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: 'rgba(0,89,184,0.06)' }} content={<ChartTooltip />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="baseline" name="Baseline" fill={CHART.neutral} radius={[0, 4, 4, 0]} barSize={11} />
                <Bar dataKey="current" name="Current" fill={CHART.teal} radius={[0, 4, 4, 0]} barSize={11} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </>
  )
}

export default function TrendAnalysis() {
  const { token } = useAuth()
  const [baselineStart, setBaselineStart] = useState('')
  const [baselineEnd, setBaselineEnd] = useState('')
  const [currentStart, setCurrentStart] = useState('')
  const [currentEnd, setCurrentEnd] = useState('')
  const [report, setReport] = useState<TrendReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Once analysis runs, collapse the (tall) date form into a compact bar so the
  // results get the space. The user can expand it again to change windows.
  const [formCollapsed, setFormCollapsed] = useState(false)

  /**
   * Fill both windows from a preset: the current window is the last `days`
   * days, and the baseline is the equal-length window immediately before it
   * (adjacent, non-overlapping).
   */
  function applyPreset(days: number) {
    const now = new Date()
    const currentStartDate = new Date(now.getTime() - days * DAY_MS)
    const baselineStartDate = new Date(currentStartDate.getTime() - days * DAY_MS)
    setCurrentEnd(toLocalInput(now))
    setCurrentStart(toLocalInput(currentStartDate))
    setBaselineEnd(toLocalInput(currentStartDate))
    setBaselineStart(toLocalInput(baselineStartDate))
    setError(null)
  }

  // Auto-fill sensible defaults on first load (last 7 days vs the prior 7).
  useEffect(() => {
    applyPreset(7)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function validateWindows(): string | null {
    if (!baselineStart || !baselineEnd || !currentStart || !currentEnd) {
      return 'All date fields are required.'
    }
    if (baselineStart >= baselineEnd) {
      return 'Baseline start must be before baseline end.'
    }
    if (currentStart >= currentEnd) {
      return 'Current start must be before current end.'
    }
    // Check for overlap: windows overlap if one starts before the other ends
    if (baselineStart < currentEnd && currentStart < baselineEnd) {
      return 'Baseline and current windows must not overlap.'
    }
    return null
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setReport(null)

    const validationError = validateWindows()
    if (validationError) {
      setError(validationError)
      return
    }

    if (!token) return
    setLoading(true)

    const body: TrendRequest = {
      baseline_window: { start: baselineStart, end: baselineEnd },
      current_window: { start: currentStart, end: currentEnd },
    }

    try {
      const result = await runTrends(token, body)
      setReport(result)
      setFormCollapsed(true)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 422) {
          const detail = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail)
          setError(`Validation error: ${detail}`)
        } else {
          setError(`Failed to run trend analysis: ${err.message}`)
        }
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <AdminLayout>
      <div className={`trend-analysis ${styles.page}`}>
        <h1>Trend Analysis</h1>

        {report && formCollapsed ? (
          /* Compact summary bar shown while results are on screen. */
          <div className={styles.trendWindowBar}>
            <div className={styles.trendWindowChips}>
              <span className={styles.trendWindowChip}>
                <span className={styles.trendWindowLabel}>Baseline</span>
                {fmtDate(baselineStart)} – {fmtDate(baselineEnd)}
              </span>
              <span className={styles.trendWindowVs}>vs</span>
              <span className={`${styles.trendWindowChip} ${styles.trendWindowChipCurrent}`}>
                <span className={styles.trendWindowLabel}>Current</span>
                {fmtDate(currentStart)} – {fmtDate(currentEnd)}
              </span>
            </div>
            <Button
              type="button"
              variant="outline"
              size="small"
              onClick={() => setFormCollapsed(false)}
            >
              Change windows
            </Button>
          </div>
        ) : (
          <>
            <p className={styles.subtitle}>
              Compare a current period against the period right before it. Use a
              quick preset or fine-tune the dates below.
            </p>

            <div className={styles.presetRow}>
              <Button type="button" variant="outline" size="small" onClick={() => applyPreset(7)}>
                Last 7 days
              </Button>
              <Button type="button" variant="outline" size="small" onClick={() => applyPreset(30)}>
                Last 30 days
              </Button>
              <Button type="button" variant="outline" size="small" onClick={() => applyPreset(90)}>
                Last 90 days
              </Button>
            </div>

            <form onSubmit={handleSubmit} aria-label="Trend analysis form" className={styles.form}>
          {error && (
            <div className={styles.error} role="alert">{error}</div>
          )}

          <fieldset>
            <legend>Baseline Time Window</legend>
            <div className={styles.formField}>
              <label htmlFor="baseline-start">Start</label>
              <input
                id="baseline-start"
                type="datetime-local"
                className={styles.input}
                value={baselineStart}
                onChange={(e) => setBaselineStart(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="baseline-end">End</label>
              <input
                id="baseline-end"
                type="datetime-local"
                className={styles.input}
                value={baselineEnd}
                onChange={(e) => setBaselineEnd(e.target.value)}
                required
                disabled={loading}
              />
            </div>
          </fieldset>

          <fieldset>
            <legend>Current Time Window</legend>
            <div className={styles.formField}>
              <label htmlFor="current-start">Start</label>
              <input
                id="current-start"
                type="datetime-local"
                className={styles.input}
                value={currentStart}
                onChange={(e) => setCurrentStart(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="current-end">End</label>
              <input
                id="current-end"
                type="datetime-local"
                className={styles.input}
                value={currentEnd}
                onChange={(e) => setCurrentEnd(e.target.value)}
                required
                disabled={loading}
              />
            </div>
          </fieldset>

              <Button type="submit" variant="primary" disabled={loading}>
                {loading ? 'Analyzing…' : 'Run Analysis'}
              </Button>
            </form>
          </>
        )}

        {report && (
          <div className="trend-report" aria-live="polite">
            <h2>Trend Report</h2>

            <TrendVisuals report={report} />

            <section aria-labelledby="theme-spikes-heading">
              <h3 id="theme-spikes-heading">Theme Spikes</h3>
              {report.theme_spikes.length === 0 ? (
                <p>No theme spikes detected.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="Theme spikes">
                    <thead>
                      <tr>
                        <th>Theme</th>
                        <th>Baseline Count</th>
                        <th>Current Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.theme_spikes.map((spike) => (
                        <tr key={spike.theme}>
                          <td>{spike.theme}</td>
                          <td>{spike.baseline}</td>
                          <td>{spike.current}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section aria-labelledby="sentiment-shifts-heading">
              <h3 id="sentiment-shifts-heading">Sentiment Shifts</h3>
              {report.sentiment_shifts.length === 0 ? (
                <p>No sentiment shifts detected.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="Sentiment shifts">
                    <thead>
                      <tr>
                        <th>Sentiment</th>
                        <th>Baseline Ratio</th>
                        <th>Current Ratio</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.sentiment_shifts.map((shift) => (
                        <tr key={shift.sentiment}>
                          <td>{shift.sentiment}</td>
                          <td>{(shift.baseline_ratio * 100).toFixed(1)}%</td>
                          <td>{(shift.current_ratio * 100).toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section aria-labelledby="severity-escalations-heading">
              <h3 id="severity-escalations-heading">Severity Escalations</h3>
              {report.severity_escalations.length === 0 ? (
                <p>No severity escalations detected.</p>
              ) : (
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="Severity escalations">
                    <thead>
                      <tr>
                        <th>Scope</th>
                        <th>Baseline Avg</th>
                        <th>Current Avg</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.severity_escalations.map((esc) => (
                        <tr key={esc.scope}>
                          <td>{esc.scope}</td>
                          <td>{esc.baseline_severity.toFixed(2)}</td>
                          <td>{esc.current_severity.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </AdminLayout>
  )
}
