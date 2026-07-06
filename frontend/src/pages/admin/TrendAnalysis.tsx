import { useState, type FormEvent } from 'react'
import { useAuth } from '../../context/AuthContext'
import { runTrends, ApiError, type TrendRequest, type TrendReport } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import styles from './admin.module.css'

export default function TrendAnalysis() {
  const { token } = useAuth()
  const [baselineStart, setBaselineStart] = useState('')
  const [baselineEnd, setBaselineEnd] = useState('')
  const [currentStart, setCurrentStart] = useState('')
  const [currentEnd, setCurrentEnd] = useState('')
  const [report, setReport] = useState<TrendReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

        {report && (
          <div className="trend-report" aria-live="polite">
            <h2>Trend Report</h2>

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
                          <td>{spike.baseline_count}</td>
                          <td>{spike.current_count}</td>
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
                        <th>Category</th>
                        <th>Baseline Avg</th>
                        <th>Current Avg</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.severity_escalations.map((esc) => (
                        <tr key={esc.category}>
                          <td>{esc.category}</td>
                          <td>{esc.baseline_avg.toFixed(2)}</td>
                          <td>{esc.current_avg.toFixed(2)}</td>
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
