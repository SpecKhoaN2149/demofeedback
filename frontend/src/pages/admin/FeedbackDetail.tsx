import { useEffect, useState, useCallback, type FormEvent } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import {
  getAdminFeedback,
  listComments,
  createComment,
  deleteFeedback,
  type FeedbackRow,
  type TicketComment,
  ApiError,
} from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Card from '../../components/ui/Card/Card'
import Button from '../../components/ui/Button/Button'
import Alert from '../../components/ui/Alert/Alert'
import Textarea from '../../components/ui/Textarea/Textarea'
import Badge from '../../components/ui/Badge/Badge'
import EnrichmentInsights from '../../components/nlp/EnrichmentInsights'
import EnrichmentStatusBadge from '../../components/nlp/EnrichmentStatusBadge'
import SourceBadge from '../../components/nlp/SourceBadge'
import SeverityBadge from '../../components/nlp/SeverityBadge'
import styles from './admin.module.css'

/**
 * Admin feedback detail (route: /admin/feedback/:id).
 *
 * Displays a single unified Feedback record: the raw text and metadata,
 * source/platform/channel attribution (via the pure `sourceDisplay` helper),
 * the NLP enrichment output, and the triage outcome. When the feedback is
 * linked to a ticket, a comments panel lists the ticket's staff comments and
 * lets an admin add a new one (Req 6.2, 6.3, 6.4, 7.5). When no ticket is
 * linked, it explains that comments become available once a ticket exists.
 */
export default function FeedbackDetail() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()
  const navigate = useNavigate()

  const [feedback, setFeedback] = useState<FeedbackRow | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Comments state (only relevant when the feedback has a linked ticket).
  const [comments, setComments] = useState<TicketComment[]>([])
  const [commentsError, setCommentsError] = useState<string | null>(null)
  const [newComment, setNewComment] = useState('')
  const [posting, setPosting] = useState(false)
  const [postError, setPostError] = useState<string | null>(null)

  const [deleting, setDeleting] = useState(false)

  const ticketId = feedback?.ticket_id ?? null

  async function handleDelete() {
    if (!token || !feedback) return
    const linked = feedback.ticket_id != null
    const message = linked
      ? 'This feedback is linked to a ticket. Deleting it will also permanently delete that ticket, its comments, and every feedback linked to it. This cannot be undone. Continue?'
      : 'Permanently delete this feedback? This cannot be undone.'
    if (!window.confirm(message)) return
    setDeleting(true)
    try {
      await deleteFeedback(token, feedback.feedback_id)
      navigate('/admin/queue')
    } catch (err) {
      setDeleting(false)
      window.alert(
        err instanceof ApiError ? `Delete failed: ${err.message}` : 'Delete failed. Please try again.'
      )
    }
  }

  // ── Load the feedback record ──────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token || !id) return
      setLoading(true)
      setError(null)
      try {
        const data = await getAdminFeedback(token, id)
        if (!cancelled) setFeedback(data)
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError) {
            setError(
              err.status === 404
                ? 'Feedback not found.'
                : `Failed to load feedback: ${err.message}`
            )
          } else {
            setError('Unable to connect to the server. Please try again.')
          }
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token, id])

  // ── Load comments for the linked ticket ──────────────────────────────────
  const loadComments = useCallback(async () => {
    if (!token || !ticketId) return
    setCommentsError(null)
    try {
      const items = await listComments(token, ticketId)
      setComments(items)
    } catch (err) {
      if (err instanceof ApiError) {
        setCommentsError(`Failed to load comments: ${err.message}`)
      } else {
        setCommentsError('Unable to load comments. Please try again.')
      }
    }
  }, [token, ticketId])

  useEffect(() => {
    if (ticketId) {
      loadComments()
    } else {
      setComments([])
    }
  }, [ticketId, loadComments])

  // ── Post a new comment ────────────────────────────────────────────────────
  async function handleAddComment(e: FormEvent) {
    e.preventDefault()
    if (!token || !ticketId) return
    if (!newComment.trim()) {
      setPostError('Comment text cannot be empty.')
      return
    }
    setPosting(true)
    setPostError(null)
    try {
      await createComment(token, ticketId, newComment.trim())
      setNewComment('')
      await loadComments()
    } catch (err) {
      if (err instanceof ApiError) {
        setPostError(`Failed to post comment: ${err.message}`)
      } else {
        setPostError('Unable to post comment. Please try again.')
      }
    } finally {
      setPosting(false)
    }
  }

  const status = feedback?.enrichment_status
  const result = feedback?.enrichment_result ?? null

  return (
    <AdminLayout>
      <div className={styles.page}>
        <div className={styles.detailActions}>
          <Button
            type="button"
            variant="ghost"
            size="small"
            onClick={() => navigate(-1)}
          >
            ← Back
          </Button>
          {feedback && (
            <Button
              type="button"
              variant="outline"
              size="small"
              className={styles.dangerBtn}
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? 'Deleting…' : 'Delete feedback'}
            </Button>
          )}
        </div>

        <h1>Feedback detail</h1>

        {loading && <p aria-live="polite">Loading feedback…</p>}
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {feedback && (
          <div className={styles.detailGrid}>
            <Card bordered>
              <h2>Feedback</h2>
              <dl className={styles.detailList}>
                <div className={styles.detailRow}>
                  <dt>Source</dt>
                  <dd>
                    <SourceBadge
                      sourceType={feedback.source_type}
                      platform={feedback.platform}
                      channel={feedback.channel}
                    />
                    {feedback.location_city && (
                      <span className={styles.locationHint}>
                        {' · '}
                        {feedback.location_city}
                        {feedback.location_state ? `, ${feedback.location_state}` : ''}
                      </span>
                    )}
                  </dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Sentiment</dt>
                  <dd>{feedback.sentiment ?? '—'}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Severity</dt>
                  <dd>
                    <SeverityBadge
                      severity={feedback.severity}
                      reasoning={feedback.severity_reasoning}
                    />
                  </dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Department</dt>
                  <dd>{feedback.department ?? '—'}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Decision</dt>
                  <dd>
                    {feedback.triage_outcome ?? '—'}
                    {feedback.needs_review && (
                      <>
                        {' '}
                        <Badge color="warning">Needs review</Badge>
                      </>
                    )}
                  </dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Ticket</dt>
                  <dd>
                    {feedback.ticket_id ? (
                      <Link
                        to={`/admin/tickets/${feedback.ticket_id}`}
                        className={styles.rowLink}
                      >
                        {feedback.ticket_id} →
                      </Link>
                    ) : (
                      'No ticket linked'
                    )}
                  </dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Submitted</dt>
                  <dd>{new Date(feedback.created_at).toLocaleString()}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Message</dt>
                  <dd>{feedback.text}</dd>
                </div>
              </dl>
            </Card>

            <Card bordered>
              <div className={styles.nlpHeader}>
                <h2>NLP analysis</h2>
                <EnrichmentStatusBadge status={status} />
              </div>

              {status === 'completed' && result ? (
                <EnrichmentInsights data={result} hideSeverity />
              ) : status === 'pending' ? (
                <Alert severity="info">
                  Analysis is still running. Refresh in a moment to see themes,
                  severity, and language.
                </Alert>
              ) : (
                <Alert severity="warning">
                  No NLP analysis is available for this feedback. This usually
                  means enrichment failed or the NLP service is not configured
                  (missing GEMINI_API_KEY).
                </Alert>
              )}
            </Card>

            <Card bordered className={styles.commentsCard}>
              <h2>Ticket comments</h2>

              {!ticketId ? (
                <Alert severity="info">
                  No ticket linked — comments available once a ticket is
                  created.
                </Alert>
              ) : (
                <>
                  {commentsError && (
                    <div className={styles.error} role="alert">
                      {commentsError}
                    </div>
                  )}

                  {comments.length === 0 && !commentsError ? (
                    <p className={styles.nlpEmpty}>No comments yet.</p>
                  ) : (
                    <ul className={styles.commentList}>
                      {comments.map((c) => (
                        <li key={c.id} className={styles.comment}>
                          <div className={styles.commentMeta}>
                            <span className={styles.commentAuthor}>
                              {c.author}
                            </span>
                            <span className={styles.commentTime}>
                              {new Date(c.created_at).toLocaleString()}
                            </span>
                          </div>
                          <p className={styles.commentText}>{c.text}</p>
                        </li>
                      ))}
                    </ul>
                  )}

                  <form onSubmit={handleAddComment} className={styles.commentForm}>
                    <Textarea
                      label="Add a comment"
                      rows={3}
                      value={newComment}
                      onChange={(e) => setNewComment(e.target.value)}
                      error={postError ?? undefined}
                      placeholder="Write an internal note…"
                    />
                    <Button type="submit" disabled={posting}>
                      {posting ? 'Posting…' : 'Add comment'}
                    </Button>
                  </form>
                </>
              )}
            </Card>
          </div>
        )}
      </div>
    </AdminLayout>
  )
}
