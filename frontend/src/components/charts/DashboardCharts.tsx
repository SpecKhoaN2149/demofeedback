/**
 * Dashboard analytics charts (Recharts) — dark "command center" theme.
 *
 * Four visuals off GET /api/admin/analytics, styled as glassy dark tiles with
 * gradient fills, glowing strokes, and a shared custom tooltip:
 *  - Severity distribution (1-10 gradient bars, color-banded)
 *  - Sentiment over time (glowing stacked area, daily)
 *  - Feedback by department (horizontal gradient bars)
 *  - Feedback by source (neon donut)
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import type { AnalyticsResponse } from '../../api/client'
import {
  CHART,
  SOURCE_COLOR,
  severityColor,
  ChartTooltip,
} from './chartTheme'
import styles from './DashboardCharts.module.css'

/** Prettify a source/platform key for display. */
function sourceLabel(key: string): string {
  if (key === 'x') return 'X'
  if (key === 'direct') return 'Direct'
  return key.charAt(0).toUpperCase() + key.slice(1)
}

/** Shorten an ISO date (YYYY-MM-DD) to "M/D" for compact axis ticks. */
function shortDate(iso: string): string {
  const parts = iso.split('-')
  if (parts.length !== 3) return iso
  return `${Number(parts[1])}/${Number(parts[2])}`
}

const AXIS_TICK = { fontSize: 12, fill: CHART.axis }
const SMALL_TICK = { fontSize: 11, fill: CHART.axis }

interface Props {
  analytics: AnalyticsResponse
}

export default function DashboardCharts({ analytics }: Props) {
  const severityData = Object.entries(analytics.severity_distribution ?? {})
    .map(([sev, count]) => ({ severity: Number(sev), count }))
    .sort((a, b) => a.severity - b.severity)

  const departmentData = Object.entries(analytics.by_department ?? {})
    .map(([department, count]) => ({ department, count }))
    .sort((a, b) => b.count - a.count)

  const sourceData = Object.entries(analytics.by_source ?? {})
    .map(([source, count]) => ({ source, label: sourceLabel(source), count }))
    .sort((a, b) => b.count - a.count)

  const trendData = (analytics.time_series ?? []).map((p) => ({
    ...p,
    label: shortDate(p.date),
  }))

  const hasSeverity = severityData.some((d) => d.count > 0)
  const hasDepartments = departmentData.length > 0
  const hasSources = sourceData.length > 0
  const hasTrend = trendData.some((d) => d.total > 0)

  return (
    <div className={styles.chartGrid}>
      {/* Severity distribution ------------------------------------------------ */}
      <div className={styles.chartCard}>
        <div className={styles.chartHeader}>
          <h3 className={styles.chartTitle}>Severity distribution</h3>
          <span className={styles.chartMeta}>
            Avg{' '}
            {analytics.average_severity != null
              ? `${analytics.average_severity}/10`
              : '—'}
          </span>
        </div>
        {hasSeverity ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={severityData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
              <defs>
                {severityData.map((d) => {
                  const c = severityColor(d.severity)
                  return (
                    <linearGradient key={d.severity} id={`sev-${d.severity}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={c} stopOpacity={0.95} />
                      <stop offset="100%" stopColor={c} stopOpacity={0.35} />
                    </linearGradient>
                  )
                })}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
              <XAxis
                dataKey="severity"
                tick={AXIS_TICK}
                axisLine={{ stroke: CHART.axisLine }}
                tickLine={false}
              />
              <YAxis allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <Tooltip
                cursor={{ fill: 'rgba(0,89,184,0.06)' }}
                content={<ChartTooltip labelFormatter={(l) => `Severity ${l}/10`} hideName />}
              />
              <Bar dataKey="count" name="Feedback" radius={[5, 5, 0, 0]}>
                {severityData.map((d) => (
                  <Cell key={d.severity} fill={`url(#sev-${d.severity})`} stroke={severityColor(d.severity)} strokeOpacity={0.5} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className={styles.empty}>No severity data yet.</p>
        )}
      </div>

      {/* Sentiment trend over time ------------------------------------------- */}
      <div className={styles.chartCard}>
        <div className={styles.chartHeader}>
          <h3 className={styles.chartTitle}>Sentiment over time</h3>
        </div>
        {hasTrend ? (
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={trendData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }}>
              <defs>
                <linearGradient id="gNeg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.red} stopOpacity={0.55} />
                  <stop offset="95%" stopColor={CHART.red} stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="gNeu" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.neutral} stopOpacity={0.5} />
                  <stop offset="95%" stopColor={CHART.neutral} stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="gPos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.green} stopOpacity={0.55} />
                  <stop offset="95%" stopColor={CHART.green} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
              <XAxis
                dataKey="label"
                tick={SMALL_TICK}
                axisLine={{ stroke: CHART.axisLine }}
                tickLine={false}
                minTickGap={16}
              />
              <YAxis allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12, color: CHART.axis }} />
              <Area
                type="monotone"
                dataKey="negative"
                stackId="1"
                stroke={CHART.red}
                strokeWidth={2}
                fill="url(#gNeg)"
                name="Negative"
              />
              <Area
                type="monotone"
                dataKey="neutral"
                stackId="1"
                stroke={CHART.neutral}
                strokeWidth={2}
                fill="url(#gNeu)"
                name="Neutral"
              />
              <Area
                type="monotone"
                dataKey="positive"
                stackId="1"
                stroke={CHART.green}
                strokeWidth={2}
                fill="url(#gPos)"
                name="Positive"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <p className={styles.empty}>No trend data yet.</p>
        )}
      </div>

      {/* By department ------------------------------------------------------- */}
      <div className={styles.chartCard}>
        <div className={styles.chartHeader}>
          <h3 className={styles.chartTitle}>Feedback by department</h3>
        </div>
        {hasDepartments ? (
          <ResponsiveContainer width="100%" height={Math.max(220, departmentData.length * 40)}>
            <BarChart
              data={departmentData}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <defs>
                <linearGradient id="deptBar" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor={CHART.primary} stopOpacity={0.5} />
                  <stop offset="100%" stopColor={CHART.cyan} stopOpacity={0.95} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <YAxis
                type="category"
                dataKey="department"
                width={140}
                tick={{ fontSize: 12, fill: '#334155' }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: 'rgba(0,89,184,0.06)' }}
                content={<ChartTooltip hideName />}
              />
              <Bar dataKey="count" name="Feedback" fill="url(#deptBar)" radius={[0, 5, 5, 0]} barSize={18} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className={styles.empty}>No department data yet.</p>
        )}
      </div>

      {/* By source ----------------------------------------------------------- */}
      <div className={styles.chartCard}>
        <div className={styles.chartHeader}>
          <h3 className={styles.chartTitle}>Feedback by source</h3>
        </div>
        {hasSources ? (
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={sourceData}
                dataKey="count"
                nameKey="label"
                cx="50%"
                cy="50%"
                innerRadius={58}
                outerRadius={92}
                paddingAngle={3}
                stroke="#ffffff"
                strokeWidth={2}
              >
                {sourceData.map((d) => (
                  <Cell key={d.source} fill={SOURCE_COLOR[d.source] ?? CHART.cyan} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltip hideName />} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12, color: CHART.axis }} />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <p className={styles.empty}>No source data yet.</p>
        )}
      </div>
    </div>
  )
}
