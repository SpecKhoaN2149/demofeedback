import { useParams, useNavigate } from 'react-router-dom'
import { usePolling } from '../hooks/usePolling'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import ProgressBar from '../components/ui/ProgressBar/ProgressBar'
import Alert from '../components/ui/Alert/Alert'
import Button from '../components/ui/Button/Button'
import styles from './StatusTracker.module.css'

/**
 * Maps a progress_state and sentiment to the appropriate user-facing message.
 * Exported for testing (Property 7).
 */
export function getStatusMessage(
  progressState: number,
  sentiment: 'negative' | 'positive' | 'neutral'
): string {
  switch (progressState) {
    case 25:
      return 'Awaiting Review'
    case 50:
      return 'Spectrum is working on this.'
    case 75:
      return 'Almost there — resolution in progress.'
    case 100:
      if (sentiment === 'positive') {
        return 'Praise received & noted!'
      }
      if (sentiment === 'negative') {
        return 'Your issue has been resolved.'
      }
      // neutral sorted to negative then resolved, or sorted to positive
      return 'Your issue has been resolved.'
    default:
      return 'Spectrum is working on this.'
  }
}

/**
 * StatusTracker component — Pages 4A (negative), 4B (positive), 4C (neutral).
 *
 * Renders a branded progress experience wrapped in the Navigation_Shell. The
 * ProgressBar sits inside a centered Card (max-width 600px) with the progress
 * percentage shown above the bar and the status message below it using the lg
 * font-size token. Uses the usePolling hook for real-time updates. Handles:
 * - Missing submission ID (error Alert, no polling)
 * - Pulsing animation at 25% (neutral awaiting review)
 * - Connection lost state with an error Alert and outline retry Button
 * - Success Alert at 100% completion
 * - Sentiment-specific completion messages at 100%
 *
 * Requirements: 6.1-6.6, 7.1-7.3, 8.1-8.7, 10.1-10.5, 12.5
 */
export default function StatusTracker() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const submissionId = id ?? null

  const { status, error, isComplete, connectionLost, retry } = usePolling(submissionId)

  // Requirement 6.6, 7.3: Missing submission ID — display error, no polling
  if (!submissionId) {
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card bordered className={styles.card}>
            <h1 className={styles.title}>Submission not found</h1>
            <Alert severity="error">
              Unable to locate your submission. Please check the URL and try
              again.
            </Alert>
            <div className={styles.retryWrapper}>
              <Button variant="outline" onClick={() => navigate('/status')}>
                Look up a submission
              </Button>
            </div>
          </Card>
        </div>
      </NavigationShell>
    )
  }

  // Determine current display values
  const progressState = status?.progress_state ?? null
  const sentiment = status?.sentiment ?? null

  // Still loading first response and no error
  if (!status && !error && !connectionLost) {
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card className={styles.card}>
            <h1 className={styles.title}>Checking submission status…</h1>
            <p className={styles.percentage}>0%</p>
            <ProgressBar value={0} pulsing />
          </Card>
        </div>
      </NavigationShell>
    )
  }

  // Connection lost after 10 consecutive failures (Requirement 12.5, 10.4)
  if (connectionLost) {
    const lastKnown = status?.progress_state ?? 0
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card className={styles.card}>
            <h1 className={styles.title}>Status Tracker</h1>
            {status && (
              <>
                <p className={styles.percentage}>{lastKnown}%</p>
                <ProgressBar value={lastKnown} />
              </>
            )}
            <Alert severity="error">
              Connection to the server has been lost.
            </Alert>
            <div className={styles.retryWrapper}>
              <Button variant="outline" onClick={retry}>
                Retry
              </Button>
            </div>
          </Card>
        </div>
      </NavigationShell>
    )
  }

  // Normal display with status data
  const currentProgress = progressState ?? 0
  const currentSentiment = sentiment ?? 'neutral'
  const message = getStatusMessage(currentProgress, currentSentiment)
  const isPulsing = currentProgress === 25

  return (
    <NavigationShell>
      <div className={styles.container}>
        <Card className={styles.card}>
          <h1 className={styles.title}>Status Tracker</h1>

          {/* Progress percentage above the bar (Requirement 10.1) */}
          <p className={styles.percentage}>{currentProgress}%</p>

          {/* ProgressBar inside the Card (Requirements 10.1, 6.x) */}
          <ProgressBar value={currentProgress} pulsing={isPulsing} />

          {/* Status message below the bar in lg font-size (Requirement 10.2) */}
          <p className={styles.message} aria-live="polite">
            {message}
          </p>

          {/* Subtle confirmation that the NLP enrichment finished analyzing. */}
          {status?.enrichment_status === 'completed' && (
            <p className={styles.analyzed}>✓ We've analyzed your feedback.</p>
          )}

          {/* Success Alert at 100% completion (Requirement 10.3) */}
          {isComplete && (
            <>
              <Alert severity="success">Thank you for your feedback!</Alert>
              <div className={styles.retryWrapper}>
                <Button variant="primary" onClick={() => navigate('/')}>
                  Submit another response
                </Button>
              </div>
            </>
          )}
        </Card>
      </div>
    </NavigationShell>
  )
}
