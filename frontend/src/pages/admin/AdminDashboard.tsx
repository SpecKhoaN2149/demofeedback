import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getAnalytics, resetDemo, type AnalyticsResponse, ApiError } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import DashboardCharts from '../../components/charts/DashboardCharts'
import FeedbackMap from '../../components/charts/FeedbackMap'
import FeedbackTable from '../../components/admin/FeedbackTable'
import { CHART } from '../../components/charts/chartTheme'
import styles from './dashboard.module.css'

/** Human-friendly labels for triage outcomes and the null/unclassified bucket. */
const TRIAGE_LABELS: Record<string, string> = {
  action_required: 'Action required',
  no_action: 'No action',
  unclassified: 'Awaiting review',
}

/** Accent color per sentiment bucket for the neon KPI top-bar. */
const SENTIMENT_ACCENT: Record<string, string> = {
  negative: CHART.red,
  neutral: CHART.neutral,
  positive: CHART.green,
}

const TRIAGE_ACCENT: Record<string, string> = {
  action_required: CHART.orange,
  no_action: CHART.teal,
  unclassified: CHART.violet,
}

/** A single accent-topped KPI tile. When `to` is set it becomes a link. */
function Kpi({
  value,
  label,
  hint,
  accent,
  to,
}: {
  value: string | number
  label: string
  hint?: string
  accent: string
  /** Optional route — renders the tile as a clickable link when provided. */
  to?: string
}) {
  const style = { ['--kpi-accent' as string]: accent }
  const inner = (
    <>
      <div className={styles.kpiValue}>{value}</div>
      <div className={styles.kpiLabel}>{label}</div>
      {hint && <div className={styles.kpiHint}>{hint}</div>}
    </>
  )

  if (to) {
    return (
      <Link to={to} className={`${styles.kpi} ${styles.kpiLink}`} style={style}>
        {inner}
        <span className={styles.kpiArrow} aria-hidden="true">→</span>
      </Link>
    )
  }

  return (
    <div className={styles.kpi} style={style}>
      {inner}
    </div>
  )
}

export default function AdminDashboard() {
  const { token } = useAuth()
  const [data, setData] = useState<AnalyticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [resetting, setResetting] = useState(false)
  const [resetMsg, setResetMsg] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchAnalytics() {
      if (!token) return
      setLoading(true)
      setError(null)

      try {
        const response = await getAnalytics(token)
        if (!cancelled) setData(response)
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError) {
            setError(`Failed to load dashboard: ${err.message}`)
          } else {
            setError('Unable to connect to the server. Please try again.')
          }
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchAnalytics()
    return () => {
      cancelled = true
    }
  }, [token, refreshKey])

  async function handleResetDemo() {
    if (!token || resetting) return
    const ok = window.confirm(
      'Reset demo data?\n\nThis wipes ALL current feedback, tickets, and comments, ' +
        'then restores the fresh mock dataset (Denver outage ticket open, no comments). ' +
        'This cannot be undone.'
    )
    if (!ok) return

    setResetting(true)
    setResetMsg(null)
    try {
      const result = await resetDemo(token)
      setResetMsg(
        `Demo reset — seeded ${result.seeded.feedback} feedback, ${result.seeded.tickets} tickets.`
      )
      setRefreshKey((k) => k + 1)
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : 'Unable to reach the server.'
      setResetMsg(`Reset failed: ${msg}`)
    } finally {
      setResetting(false)
    }
  }

  const renderHeader = (subtitle: string) => (
    <div className={styles.header}>
      <div>
        <h1 className={styles.title}>
          <span className={styles.titleAccent} aria-hidden="true" />
          Admin Dashboard
        </h1>
        <p className={styles.subtitle}>{subtitle}</p>
      </div>
      <div className={styles.headerActions}>
        <button
          type="button"
          className={styles.resetBtn}
          onClick={handleResetDemo}
          disabled={resetting}
          title="Wipe all data and restore the fresh mock demo dataset"
        >
          {resetting ? 'Resetting…' : 'Reset Demo Data'}
        </button>
        <span className={styles.livePill}>
          <span className={styles.liveDot} aria-hidden="true" />
          Live
        </span>
      </div>
    </div>
  )

  const resetBanner = resetMsg && (
    <div className={styles.resetBanner} role="status">
      {resetMsg}
    </div>
  )

  if (loading) {
    return (
      <AdminLayout>
        <div className={styles.canvas}>
          {renderHeader('Loading analytics…')}
          <p className={styles.stateMsg}>Loading dashboard…</p>
        </div>
      </AdminLayout>
    )
  }

  if (error) {
    return (
      <AdminLayout>
        <div className={styles.canvas}>
          {renderHeader('Feedback intelligence overview')}
          <div className={styles.error} role="alert">{error}</div>
        </div>
      </AdminLayout>
    )
  }

  if (!data) {
    return (
      <AdminLayout>
        <div className={styles.canvas}>
          {renderHeader('Feedback intelligence overview')}
          <p className={styles.stateMsg}>No data available.</p>
        </div>
      </AdminLayout>
    )
  }

  // Defensive defaults so a missing field can never crash the render.
  const bySentiment = data.by_sentiment ?? {}
  const byTriage = data.by_triage_outcome ?? {}
  const totals = data.totals ?? { total: 0, tickets_linked: 0, needs_review: 0 }
  const total =
    totals.total ?? Object.values(bySentiment).reduce((sum, n) => sum + n, 0)

  return (
    <AdminLayout>
      <div className={styles.canvas}>
        {renderHeader('Feedback intelligence across every channel')}
        {resetBanner}

        {/* All feedback table */}
        <section className={styles.section} aria-labelledby="all-feedback-heading">
          <h2 id="all-feedback-heading" className={styles.sectionTitle}>All Feedback</h2>
          <FeedbackTable />
        </section>

        {/* Primary KPIs */}
        <section className={styles.section} aria-labelledby="overview-heading">
          <h2 id="overview-heading" className={styles.sectionTitle}>Overview</h2>
          <div className={styles.kpiGrid}>
            <Kpi value={total} label="Total Feedback" accent={CHART.cyan} />
            <Kpi
              value={totals.tickets_linked}
              label="Linked to Tickets"
              accent={CHART.primary}
            />
            <Kpi
              value={totals.needs_review}
              label="Needs Review"
              accent={CHART.amber}
              to="/admin/queue"
            />
            <Kpi
              value={data.average_severity != null ? `${data.average_severity}` : '—'}
              label="Avg Severity"
              hint="scale 1–10"
              accent={CHART.orange}
            />
          </div>
        </section>

        {/* Charts */}
        <section className={styles.section} aria-labelledby="charts-heading">
          <h2 id="charts-heading" className={styles.sectionTitle}>Analytics</h2>
          <DashboardCharts analytics={data} />
        </section>

        {/* Map */}
        <section className={styles.section} aria-labelledby="map-heading">
          <h2 id="map-heading" className={styles.sectionTitle}>Trends by Location</h2>
          <FeedbackMap points={data.map_points ?? []} byState={data.by_state ?? []} />
        </section>

        {/* Sentiment breakdown */}
        <section className={styles.section} aria-labelledby="sentiment-heading">
          <h2 id="sentiment-heading" className={styles.sectionTitle}>Feedback by Sentiment</h2>
          {Object.keys(bySentiment).length === 0 ? (
            <p className={styles.empty}>No feedback yet.</p>
          ) : (
            <div className={styles.kpiGrid}>
              {Object.entries(bySentiment).map(([sentiment, count]) => (
                <Kpi
                  key={sentiment}
                  value={count}
                  label={sentiment}
                  accent={SENTIMENT_ACCENT[sentiment] ?? CHART.neutral}
                  to={
                    ['negative', 'neutral', 'positive'].includes(sentiment)
                      ? `/admin/queue?sentiment=${sentiment}`
                      : undefined
                  }
                />
              ))}
            </div>
          )}
        </section>

        {/* Action-status breakdown */}
        <section className={styles.section} aria-labelledby="triage-heading">
          <h2 id="triage-heading" className={styles.sectionTitle}>Feedback by Action Status</h2>
          {Object.keys(byTriage).length === 0 ? (
            <p className={styles.empty}>No data available.</p>
          ) : (
            <div className={styles.kpiGrid}>
              {Object.entries(byTriage).map(([outcome, count]) => (
                <Kpi
                  key={outcome}
                  value={count}
                  label={TRIAGE_LABELS[outcome] ?? outcome}
                  accent={TRIAGE_ACCENT[outcome] ?? CHART.neutral}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </AdminLayout>
  )
}
