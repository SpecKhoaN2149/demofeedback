import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { getDashboard, type DashboardResponse, ApiError } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Card from '../../components/ui/Card/Card'
import EnrichmentStatusBadge, {
  type EnrichmentStatus,
} from '../../components/nlp/EnrichmentStatusBadge'
import styles from './admin.module.css'

/** Maps a sentiment key to its stat-card top-border color modifier class. */
const SENTIMENT_BORDER: Record<string, string> = {
  negative: styles.borderNegative,
  positive: styles.borderPositive,
  neutral: styles.borderNeutral,
}

export default function AdminDashboard() {
  const { token } = useAuth()
  const [data, setData] = useState<DashboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchDashboard() {
      if (!token) return
      setLoading(true)
      setError(null)

      try {
        const response = await getDashboard(token)
        if (!cancelled) {
          setData(response)
        }
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError) {
            setError(`Failed to load dashboard: ${err.message}`)
          } else {
            setError('Unable to connect to the server. Please try again.')
          }
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchDashboard()
    return () => { cancelled = true }
  }, [token])

  if (loading) {
    return (
      <AdminLayout>
        <div className={`admin-dashboard ${styles.page}`}>
          <h1>Admin Dashboard</h1>
          <p>Loading dashboard…</p>
        </div>
      </AdminLayout>
    )
  }

  if (error) {
    return (
      <AdminLayout>
        <div className={`admin-dashboard ${styles.page}`}>
          <h1>Admin Dashboard</h1>
          <div className={styles.error} role="alert">{error}</div>
        </div>
      </AdminLayout>
    )
  }

  if (!data) {
    return (
      <AdminLayout>
        <div className={`admin-dashboard ${styles.page}`}>
          <h1>Admin Dashboard</h1>
          <p>No data available.</p>
        </div>
      </AdminLayout>
    )
  }

  const { by_sentiment, by_progress_state, top_categories } = data

  const totalSubmissions =
    Object.values(by_sentiment).reduce((sum, count) => sum + count, 0)

  const statusCounts = data.enrichment_status_counts ?? {}
  const topThemes = data.top_themes ?? []
  const byLanguage = data.by_language ?? {}
  const avgSeverity = data.average_severity ?? null
  const hasNlp =
    Object.keys(statusCounts).length > 0 ||
    topThemes.length > 0 ||
    Object.keys(byLanguage).length > 0 ||
    avgSeverity != null
  const statusOrder: EnrichmentStatus[] = [
    'completed',
    'pending',
    'failed',
    'timeout',
  ]

  return (
    <AdminLayout>
      <div className={`admin-dashboard ${styles.page}`}>
        <h1>Admin Dashboard</h1>

        <section aria-labelledby="sentiment-heading">
          <h2 id="sentiment-heading">Submissions by Sentiment</h2>
          {totalSubmissions === 0 ? (
            <p>No submissions yet.</p>
          ) : (
            <div className={styles.statGrid}>
              {/* Total submissions — blue top border. */}
              <Card bordered className={`${styles.statCard} ${styles.borderTotal}`}>
                <div className={styles.statValue}>{totalSubmissions}</div>
                <div className={styles.statLabel}>Total Submissions</div>
              </Card>

              {/* One card per sentiment with a sentiment-colored top border. */}
              {Object.entries(by_sentiment).map(([sentiment, count]) => (
                <Card
                  key={sentiment}
                  bordered
                  className={`${styles.statCard} ${SENTIMENT_BORDER[sentiment] ?? styles.borderNeutral}`}
                >
                  <div className={styles.statValue}>{count}</div>
                  <div className={styles.statLabel}>{sentiment}</div>
                </Card>
              ))}
            </div>
          )}
        </section>

        <section aria-labelledby="progress-heading">
          <h2 id="progress-heading">Submissions by Progress State</h2>
          {Object.keys(by_progress_state).length === 0 ? (
            <p>No progress data available.</p>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="Counts by progress state">
                <thead>
                  <tr>
                    <th>Progress State</th>
                    <th>Submissions</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(by_progress_state).map(([state, count]) => (
                    <tr key={state}>
                      <td>{state}%</td>
                      <td>{count} {count === 1 ? 'submission' : 'submissions'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section aria-labelledby="categories-heading">
          <h2 id="categories-heading">Top Issue Categories</h2>
          {top_categories.length === 0 ? (
            <p>No negative submissions to rank.</p>
          ) : (
            <ol aria-label="Top 5 issue categories by frequency">
              {top_categories.slice(0, 5).map(({ category, count }) => (
                <li key={category}>
                  {category} — {count} {count === 1 ? 'submission' : 'submissions'}
                </li>
              ))}
            </ol>
          )}
        </section>

        {hasNlp && (
          <section aria-labelledby="nlp-heading">
            <h2 id="nlp-heading">NLP Insights</h2>

            <div className={styles.statGrid}>
              {statusOrder
                .filter((s) => statusCounts[s] != null)
                .map((s) => (
                  <Card key={s} bordered className={styles.statCard}>
                    <div className={styles.statValue}>{statusCounts[s]}</div>
                    <div className={styles.statLabel}>
                      <EnrichmentStatusBadge status={s} />
                    </div>
                  </Card>
                ))}
              {avgSeverity != null && (
                <Card bordered className={`${styles.statCard} ${styles.borderNegative}`}>
                  <div className={styles.statValue}>{avgSeverity} / 5</div>
                  <div className={styles.statLabel}>Average severity</div>
                </Card>
              )}
            </div>

            <h3>Top themes</h3>
            {topThemes.length === 0 ? (
              <p>No themes detected yet.</p>
            ) : (
              <div className={styles.themeCloud}>
                {topThemes.map(({ theme, count }) => (
                  <span key={theme} className={styles.themeCloudChip}>
                    {theme}
                    <span className={styles.themeCloudCount}>{count}</span>
                  </span>
                ))}
              </div>
            )}

            {Object.keys(byLanguage).length > 0 && (
              <>
                <h3>Languages detected</h3>
                <div className={styles.tableWrapper}>
                  <table className={styles.table} aria-label="Detected languages">
                    <thead>
                      <tr>
                        <th>Language</th>
                        <th>Submissions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(byLanguage).map(([lang, count]) => (
                        <tr key={lang}>
                          <td>{lang.toUpperCase()}</td>
                          <td>{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        )}
      </div>
    </AdminLayout>
  )
}
