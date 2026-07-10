import { useParams, useNavigate } from 'react-router-dom'
import { usePolling } from '../hooks/usePolling'
import type { FeedbackStatus, TicketComment } from '../api/client'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import Alert from '../components/ui/Alert/Alert'
import Badge from '../components/ui/Badge/Badge'
import Button from '../components/ui/Button/Button'
import styles from './StatusTracker.module.css'

/** Render model derived from a FeedbackStatus payload (Requirements 8, 9). */
export interface StatusModel {
  /** Whether a ticket is linked to this feedback. */
  hasTicket: boolean
  /** Linked ticket status, or null when no ticket is associated. */
  ticketStatus: 'open' | 'in_progress' | 'resolved' | null
  /** Comments visible to the customer, in ascending timestamp order. */
  comments: TicketComment[]
  /** Whether NLP analysis is still in progress (enrichment pending). */
  analysisInProgress: boolean
  /** Human-readable label describing where the feedback stands. */
  statusLabel: string
  /** Human-readable label for the triage outcome, or null when undecided. */
  triageLabel: string | null
}

/** Maps a triage outcome to a customer-facing label. */
function triageOutcomeLabel(
  outcome: FeedbackStatus['triage_outcome']
): string | null {
  switch (outcome) {
    case 'action_required':
      return 'Action required — we are handling this as a ticket.'
    case 'no_action':
      return 'Reviewed and retained as feedback.'
    default:
      return null
  }
}

/** Maps a linked ticket status to a customer-facing label. */
export function ticketStatusLabel(
  status: 'open' | 'in_progress' | 'resolved'
): string {
  switch (status) {
    case 'open':
      return 'Open'
    case 'in_progress':
      return 'In progress'
    case 'resolved':
      return 'Resolved'
  }
}

/** Maps a ticket status to a Badge color. */
function ticketBadgeColor(
  status: 'open' | 'in_progress' | 'resolved'
): 'success' | 'warning' | 'info' | 'neutral' {
  switch (status) {
    case 'open':
      return 'info'
    case 'in_progress':
      return 'warning'
    case 'resolved':
      return 'success'
  }
}

/**
 * Pure mapping from a FeedbackStatus payload to the component's render model.
 *
 * - When a ticket is linked, exposes its status and the ticket's comments
 *   (already ascending from the API) (Requirements 8.1, 8.4, 8.5, 9.2).
 * - When no ticket is linked, reports hasTicket=false with an empty comment
 *   list so the UI can show the "no ticket associated" message (Requirement 8.2).
 * - Reports analysisInProgress while enrichment is pending (Requirement 9.4).
 *
 * Exported as a pure helper for property testing (task 14.2).
 */
export function buildStatusModel(status: FeedbackStatus): StatusModel {
  const hasTicket = status.ticket !== null
  const analysisInProgress =
    status.analysis_in_progress || status.enrichment_status === 'pending'

  let statusLabel: string
  if (analysisInProgress) {
    statusLabel = "We're reviewing your feedback"
  } else if (status.enrichment_status === 'failed' || status.enrichment_status === 'timeout') {
    statusLabel = "We've received your feedback"
  } else if (hasTicket) {
    statusLabel = 'A ticket has been opened for your feedback'
  } else {
    statusLabel = 'Your feedback has been reviewed'
  }

  return {
    hasTicket,
    ticketStatus: status.ticket?.status ?? null,
    comments: status.comments ?? [],
    analysisInProgress,
    statusLabel,
    triageLabel: triageOutcomeLabel(status.triage_outcome),
  }
}

type StepState = 'done' | 'active' | 'upcoming'
interface ProgressStep {
  label: string
  hint?: string
  state: StepState
}

/**
 * Build the customer-facing progress flow from a status payload.
 *
 * Always starts Submitted → Analyzed → Reviewed, then branches: a linked ticket
 * expands into Opened → In progress → Resolved (reflecting the ticket status),
 * while a no-action decision ends at "Logged as feedback".
 */
export function buildStatusSteps(
  status: FeedbackStatus,
  model: StatusModel
): ProgressStep[] {
  const decided = status.triage_outcome !== null
  const steps: ProgressStep[] = [
    { label: 'Submitted', hint: 'We received your feedback', state: 'done' },
    {
      label: 'Reviewed',
      hint: 'We review and decide the next step',
      state: decided ? 'done' : 'active',
    },
  ]

  if (model.hasTicket && model.ticketStatus) {
    const ts = model.ticketStatus
    steps.push({ label: 'Ticket opened', state: 'done' })
    steps.push({
      label: 'In progress',
      state: ts === 'in_progress' || ts === 'resolved' ? 'done' : 'active',
    })
    steps.push({
      label: 'Resolved',
      state: ts === 'resolved' ? 'done' : ts === 'in_progress' ? 'active' : 'upcoming',
    })
  } else if (status.triage_outcome === 'no_action') {
    steps.push({
      label: 'Logged as feedback',
      hint: 'Kept for trends and improvements',
      state: 'done',
    })
  }

  return steps
}

/** Formats an ISO timestamp for display; falls back to the raw string. */
function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
}

/**
 * StatusTracker component — customer feedback status view.
 *
 * Renders the current enrichment status, triage outcome, any linked ticket's
 * status, and that ticket's staff comments (author + timestamp, ascending). If
 * no ticket is linked, shows a "no ticket associated" message. Uses usePolling
 * for real-time updates. Handles missing feedback ID and connection-lost states.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.4
 */
export default function StatusTracker() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const feedbackId = id ?? null

  const { status, error, connectionLost, retry } = usePolling(feedbackId)

  // Requirement 9.3: Missing feedback ID — display error, no polling
  if (!feedbackId) {
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card bordered className={styles.card}>
            <h1 className={styles.title}>Feedback not found</h1>
            <Alert severity="error">
              Unable to locate your feedback. Please check the URL and try
              again.
            </Alert>
            <div className={styles.retryWrapper}>
              <Button variant="outline" onClick={() => navigate('/status')}>
                Look up feedback
              </Button>
            </div>
          </Card>
        </div>
      </NavigationShell>
    )
  }

  // Still loading first response and no error
  if (!status && !error && !connectionLost) {
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card className={styles.card}>
            <h1 className={styles.title}>Checking feedback status…</h1>
            <p className={styles.message}>Analysis in progress</p>
          </Card>
        </div>
      </NavigationShell>
    )
  }

  // Connection lost after 10 consecutive failures
  if (connectionLost) {
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card className={styles.card}>
            <h1 className={styles.title}>Feedback status</h1>
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

  // status is guaranteed non-null here (error-only state would still have
  // rendered above only when status is also null → connectionLost path).
  if (!status) {
    return (
      <NavigationShell>
        <div className={styles.container}>
          <Card className={styles.card}>
            <h1 className={styles.title}>Feedback status</h1>
            <Alert severity="error">
              We couldn't load your feedback status right now. Please try again.
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

  const model = buildStatusModel(status)

  return (
    <NavigationShell>
      <div className={styles.container}>
        <Card className={styles.card}>
          {/* Header: title + feedback ID chip */}
          <div className={styles.header}>
            <h1 className={styles.title}>Feedback status</h1>
            <span className={styles.idChip} title={feedbackId}>
              ID: {feedbackId.slice(0, 8)}…
            </span>
          </div>

          {/* Status hero: friendly headline + optional outcome subtext */}
          <div
            className={`${styles.hero} ${
              model.analysisInProgress ? styles.heroPending : styles.heroDone
            }`}
          >
            <span className={styles.heroIcon} aria-hidden="true">
              {model.analysisInProgress ? '⏳' : model.hasTicket ? '🎫' : '✓'}
            </span>
            <div className={styles.heroText}>
              <p className={styles.heroTitle} aria-live="polite">
                {model.statusLabel}
              </p>
              {model.triageLabel && (
                <p className={styles.heroSubtitle}>{model.triageLabel}</p>
              )}
            </div>
            {model.hasTicket && model.ticketStatus && (
              <Badge color={ticketBadgeColor(model.ticketStatus)}>
                {ticketStatusLabel(model.ticketStatus)}
              </Badge>
            )}
          </div>

          {/* Progress flow reflecting where the feedback stands */}
          <section className={styles.section}>
            <h2 className={styles.sectionHeading}>Progress</h2>
            <ol className={styles.steps} aria-label="Feedback progress">
              {buildStatusSteps(status, model).map((step, i) => (
                <li
                  key={`${step.label}-${i}`}
                  className={`${styles.step} ${
                    step.state === 'done'
                      ? styles.stepDone
                      : step.state === 'active'
                        ? styles.stepActive
                        : styles.stepUpcoming
                  }`}
                >
                  <span className={styles.stepMarker} aria-hidden="true">
                    {step.state === 'done' ? '✓' : ''}
                  </span>
                  <span className={styles.stepBody}>
                    <span className={styles.stepLabel}>{step.label}</span>
                    {step.hint && <span className={styles.stepHint}>{step.hint}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </section>

          {/* Updates from our team (Req 8.1, 8.3, 8.5) */}
          {model.hasTicket ? (
            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Updates from our team</h2>
              {model.comments.length === 0 ? (
                <p className={styles.emptyComments}>
                  No updates have been posted yet. We&apos;ll add them here as
                  your ticket progresses.
                </p>
              ) : (
                <ul className={styles.commentList}>
                  {model.comments.map((comment) => (
                    <li key={comment.id} className={styles.comment}>
                      <div className={styles.commentMeta}>
                        <span className={styles.commentAuthor}>
                          {comment.author}
                        </span>
                        <span className={styles.commentTime}>
                          {formatTimestamp(comment.created_at)}
                        </span>
                      </div>
                      <p className={styles.commentText}>{comment.text}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : (
            <Alert severity="info">
              No ticket is associated with this feedback yet.
            </Alert>
          )}

          <div className={styles.retryWrapper}>
            <Button variant="primary" onClick={() => navigate('/')}>
              Submit another response
            </Button>
          </div>
        </Card>
      </div>
    </NavigationShell>
  )
}
