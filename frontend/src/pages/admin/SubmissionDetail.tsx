import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getSubmission, type Submission, ApiError } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Card from '../../components/ui/Card/Card'
import Button from '../../components/ui/Button/Button'
import Alert from '../../components/ui/Alert/Alert'
import EnrichmentInsights from '../../components/nlp/EnrichmentInsights'
import EnrichmentStatusBadge from '../../components/nlp/EnrichmentStatusBadge'
import styles from './admin.module.css'

/**
 * Admin submission detail (route: /admin/submissions/:id).
 *
 * The richest NLP surface: shows the full enrichment output (themes with
 * confidence, severity + factors, sentiment confidence, detected language)
 * alongside the raw submission fields. Explains the state when enrichment is
 * still pending or failed.
 */
export default function SubmissionDetail() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()
  const navigate = useNavigate()
  const [submission, setSubmission] = useState<Submission | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token || !id) return
      setLoading(true)
      setError(null)
      try {
        const data = await getSubmission(id, token)
        if (!cancelled) setSubmission(data)
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError) {
            setError(
              err.status === 404
                ? 'Submission not found.'
                : `Failed to load submission: ${err.message}`
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

  const status = submission?.enrichment_status
  const result = submission?.enrichment_result ?? null

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

        <h1>Submission detail</h1>

        {loading && <p aria-live="polite">Loading submission…</p>}
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {submission && (
          <div className={styles.detailGrid}>
            <Card bordered>
              <h2>Submission</h2>
              <dl className={styles.detailList}>
                <div className={styles.detailRow}>
                  <dt>Customer</dt>
                  <dd>{submission.customer_name}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Sentiment</dt>
                  <dd>{submission.sentiment}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Progress</dt>
                  <dd>{submission.progress_state}%</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>Submitted</dt>
                  <dd>{new Date(submission.created_at).toLocaleString()}</dd>
                </div>
                {submission.issue_category && (
                  <div className={styles.detailRow}>
                    <dt>Category</dt>
                    <dd>{submission.issue_category}</dd>
                  </div>
                )}
                <div className={styles.detailRow}>
                  <dt>Message</dt>
                  <dd>
                    {submission.detailed_description ||
                      submission.praise_text ||
                      submission.comment_text ||
                      submission.core_request}
                  </dd>
                </div>
              </dl>
            </Card>

            <Card bordered>
              <div className={styles.nlpHeader}>
                <h2>NLP analysis</h2>
                <EnrichmentStatusBadge status={status} />
              </div>

              {status === 'completed' && result ? (
                <EnrichmentInsights data={result} />
              ) : status === 'pending' ? (
                <Alert severity="info">
                  Analysis is still running. Refresh in a moment to see themes,
                  severity, and language.
                </Alert>
              ) : (
                <Alert severity="warning">
                  No NLP analysis is available for this submission. This usually
                  means enrichment failed or the NLP service is not configured
                  (missing GEMINI_API_KEY).
                </Alert>
              )}
            </Card>
          </div>
        )}
      </div>
    </AdminLayout>
  )
}
