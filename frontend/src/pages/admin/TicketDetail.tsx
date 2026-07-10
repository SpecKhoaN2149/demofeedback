import { useEffect, useState, useCallback, type FormEvent } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import {
  getTicketDetail,
  advanceTicket,
  listComments,
  createComment,
  getAdminFeedback,
  type TicketDetail as TicketDetailModel,
  type TicketComment,
  type FeedbackRow,
  ApiError,
} from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Card from '../../components/ui/Card/Card'
import Button from '../../components/ui/Button/Button'
import Textarea from '../../components/ui/Textarea/Textarea'
import styles from './admin.module.css'

const STATUS_PILL: Record<string, string> = {
  open: styles.statusOpen,
  in_progress: styles.statusProgress,
  resolved: styles.statusResolved,
}

function nextStatus(status: string): string {
  if (status === 'open') return 'in_progress'
  if (status === 'in_progress') return 'resolved'
  return ''
}

/**
 * Admin ticket detail (route: /admin/tickets/:id).
 *
 * Shows the ticket's metadata, the feedback records linked to it, and the
 * internal comment thread. Admins can advance the ticket's status and post
 * comments — those comments are the same ones surfaced to customers in the
 * public feedback status view, so staff notes reflect back to the customer.
 */
export default function TicketDetail() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()
  const navigate = useNavigate()

  const [ticket, setTicket] = useState<TicketDetailModel | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [advancing, setAdvancing] = useState(false)
  const [advanceError, setAdvanceError] = useState<string | null>(null)

  const [linked, setLinked] = useState<FeedbackRow[]>([])

  const [comments, setComments] = useState<TicketComment[]>([])
  const [commentsError, setCommentsError] = useState<string | null>(null)
  const [newComment, setNewComment] = useState('')
  const [posting, setPosting] = useState(false)
  const [postError, setPostError] = useState<string | null>(null)

  const loadTicket = useCallback(async () => {
    if (!token || !id) return
    setError(null)
    try {
      const data = await getTicketDetail(token, id)
      setTicket(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 404 ? 'Ticket not found.' : `Failed to load ticket: ${err.message}`)
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [token, id])

  const loadComments = useCallback(async () => {
    if (!token || !id) return
    setCommentsError(null)
    try {
      setComments(await listComments(token, id))
    } catch (err) {
      if (err instanceof ApiError) {
        setCommentsError(`Failed to load comments: ${err.message}`)
      } else {
        setCommentsError('Unable to load comments. Please try again.')
      }
    }
  }, [token, id])

  useEffect(() => {
    loadTicket()
    loadComments()
  }, [loadTicket, loadComments])

  // Hydrate the linked feedback records so we can show a readable preview of
  // each (rather than a truncated id).
  useEffect(() => {
    let cancelled = false
    async function loadLinked() {
      if (!token || !ticket || ticket.feedback_ids.length === 0) {
        setLinked([])
        return
      }
      try {
        const rows = await Promise.all(
          ticket.feedback_ids.map((fid) => getAdminFeedback(token, String(fid)))
        )
        if (!cancelled) setLinked(rows)
      } catch {
        /* Non-fatal: fall back to just the ids if a fetch fails. */
      }
    }
    loadLinked()
    return () => {
      cancelled = true
    }
  }, [token, ticket])

  async function handleAdvance() {
    if (!token || !ticket) return
    setAdvancing(true)
    setAdvanceError(null)
    try {
      await advanceTicket(token, String(ticket.ticket_id))
      await loadTicket()
    } catch (err) {
      if (err instanceof ApiError) {
        setAdvanceError(
          err.status === 409
            ? 'This ticket cannot be advanced further.'
            : `Failed to advance ticket: ${err.message}`
        )
      } else {
        setAdvanceError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setAdvancing(false)
    }
  }

  async function handleAddComment(e: FormEvent) {
    e.preventDefault()
    if (!token || !id) return
    if (!newComment.trim()) {
      setPostError('Comment text cannot be empty.')
      return
    }
    setPosting(true)
    setPostError(null)
    try {
      await createComment(token, id, newComment.trim())
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

  const status = ticket ? String(ticket.status) : ''
  const next = nextStatus(status)

  return (
    <AdminLayout>
      <div className={styles.page}>
        <Button
          type="button"
          variant="ghost"
          size="small"
          onClick={() => navigate(-1)}
          className={styles.detailBack}
        >
          ← Back
        </Button>

        <h1>Ticket detail</h1>

        {loading && <p aria-live="polite">Loading ticket…</p>}
        {error && (
          <div className={styles.error} role="alert">{error}</div>
        )}

        {ticket && (
          <div className={styles.detailGrid}>
            <Card bordered>
              <div className={styles.nlpHeader}>
                <h2>Ticket</h2>
                <span className={`${styles.statusPill} ${STATUS_PILL[status] ?? ''}`}>
                  {status.replace('_', ' ')}
                </span>
              </div>
              <dl className={styles.detailList}>
                <div className={styles.detailRow}>
                  <dt>Ticket ID</dt>
                  <dd>{String(ticket.ticket_id)}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Category</dt>
                  <dd>{ticket.issue_category}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Priority</dt>
                  <dd>{ticket.priority}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Created</dt>
                  <dd>{new Date(ticket.created_at).toLocaleString()}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Description</dt>
                  <dd>{ticket.description}</dd>
                </div>
              </dl>

              {advanceError && (
                <div className={styles.error} role="alert">{advanceError}</div>
              )}
              <div className={styles.actionRow} style={{ marginTop: '1rem' }}>
                <Button
                  variant="primary"
                  size="small"
                  onClick={handleAdvance}
                  disabled={advancing || !next}
                >
                  {advancing
                    ? 'Advancing…'
                    : next
                      ? `Advance to ${next.replace('_', ' ')}`
                      : 'Resolved'}
                </Button>
              </div>
            </Card>

            <Card bordered>
              <h2>Linked feedback</h2>
              {ticket.feedback_ids.length === 0 ? (
                <p className={styles.nlpEmpty}>No feedback linked to this ticket.</p>
              ) : (
                <ul className={styles.linkedList}>
                  {ticket.feedback_ids.map((fid) => {
                    const row = linked.find((r) => String(r.feedback_id) === String(fid))
                    return (
                      <li key={String(fid)} className={styles.linkedItem}>
                        <div className={styles.linkedBody}>
                          <p className={styles.linkedText}>
                            {row ? row.text : `${String(fid).slice(0, 8)}…`}
                          </p>
                          {row && (
                            <span className={styles.linkedMeta}>
                              {row.sentiment ?? 'unknown'}
                              {row.department ? ` · ${row.department}` : ''}
                              {row.severity != null ? ` · severity ${row.severity}/10` : ''}
                            </span>
                          )}
                        </div>
                        <Link className={styles.linkedLink} to={`/admin/feedback/${fid}`}>
                          View →
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>

            <Card bordered className={styles.commentsCard}>
              <h2>Comments</h2>
              <p className={styles.subtitle}>
                Visible to the customer in their feedback status view.
              </p>

              {commentsError && (
                <div className={styles.error} role="alert">{commentsError}</div>
              )}

              {comments.length === 0 && !commentsError ? (
                <p className={styles.nlpEmpty}>No comments yet.</p>
              ) : (
                <ul className={styles.commentList}>
                  {comments.map((c) => (
                    <li key={c.id} className={styles.comment}>
                      <div className={styles.commentMeta}>
                        <span className={styles.commentAuthor}>{c.author}</span>
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
                  placeholder="Write a note the customer will see…"
                />
                <Button type="submit" disabled={posting}>
                  {posting ? 'Posting…' : 'Add comment'}
                </Button>
              </form>
            </Card>
          </div>
        )}
      </div>
    </AdminLayout>
  )
}
