import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getQueue, sortSubmission, type QueueEntry, type SortRequest, ApiError } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import EnrichmentInsights from '../../components/nlp/EnrichmentInsights'
import EnrichmentStatusBadge from '../../components/nlp/EnrichmentStatusBadge'
import styles from './admin.module.css'

const ISSUE_CATEGORIES = [
  'billing',
  'network_speed',
  'outage',
  'support_experience',
  'device_hardware',
  'pricing',
] as const

const PAGE_SIZE = 20

export default function ReviewQueue() {
  const { token } = useAuth()
  const [items, setItems] = useState<QueueEntry[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sortingId, setSortingId] = useState<string | null>(null)
  const [sortError, setSortError] = useState<string | null>(null)
  const [selectedCategories, setSelectedCategories] = useState<Record<string, string>>({})

  const fetchQueue = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const response = await getQueue(token, PAGE_SIZE, offset)
      setItems(response.items)
      setHasMore(response.items.length === PAGE_SIZE)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load queue: ${err.message}`)
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [token, offset])

  useEffect(() => {
    fetchQueue()
  }, [fetchQueue])

  async function handleSortToNegative(submissionId: string) {
    if (!token) return
    const category = selectedCategories[submissionId]
    if (!category) {
      setSortError('Please select an issue category before sorting to negative.')
      return
    }

    setSortingId(submissionId)
    setSortError(null)
    try {
      const body: SortRequest = {
        target_sentiment: 'negative',
        issue_category: category,
      }
      await sortSubmission(token, submissionId, body)
      await fetchQueue()
    } catch (err) {
      if (err instanceof ApiError) {
        setSortError(`Sort failed: ${err.message}`)
      } else {
        setSortError('Sort failed due to a network error. Please try again.')
      }
    } finally {
      setSortingId(null)
    }
  }

  async function handleSortToPositive(submissionId: string) {
    if (!token) return

    setSortingId(submissionId)
    setSortError(null)
    try {
      const body: SortRequest = {
        target_sentiment: 'positive',
      }
      await sortSubmission(token, submissionId, body)
      await fetchQueue()
    } catch (err) {
      if (err instanceof ApiError) {
        setSortError(`Sort failed: ${err.message}`)
      } else {
        setSortError('Sort failed due to a network error. Please try again.')
      }
    } finally {
      setSortingId(null)
    }
  }

  function handleCategoryChange(submissionId: string, category: string) {
    setSelectedCategories((prev) => ({ ...prev, [submissionId]: category }))
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  function goToPage(page: number) {
    setOffset((page - 1) * PAGE_SIZE)
  }

  return (
    <AdminLayout>
      <div className={`review-queue ${styles.page}`}>
        <h1>Review Queue</h1>
        <p className={styles.subtitle}>
          Neutral submissions awaiting review
        </p>

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {sortError && (
          <div className={styles.error} role="alert">
            {sortError}
          </div>
        )}

        {loading && <p aria-live="polite">Loading queue…</p>}

        {!loading && items.length === 0 && !error && (
          <p>No neutral submissions in the queue.</p>
        )}

        {!loading && items.length > 0 && (
          <>
            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="Review queue">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Customer Name</th>
                    <th>Comment</th>
                    <th>NLP Analysis</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.submission_id}>
                      <td>{new Date(item.created_at).toLocaleString()}</td>
                      <td>
                        <Link
                          to={`/admin/submissions/${item.submission_id}`}
                          className={styles.rowLink}
                        >
                          {item.customer_name}
                        </Link>
                      </td>
                      <td className={styles.commentCell}>{item.comment_text}</td>
                      <td>
                        <div className={styles.nlpCell}>
                          <EnrichmentStatusBadge status={item.enrichment_status} />
                          {item.enrichment_summary ? (
                            <EnrichmentInsights
                              data={item.enrichment_summary}
                              compact
                            />
                          ) : (
                            <span className={styles.nlpEmpty}>
                              No analysis yet
                            </span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className={styles.actions}>
                          <div className={styles.actionRow}>
                            <select
                              aria-label={`Issue category for ${item.customer_name}`}
                              className={styles.select}
                              value={selectedCategories[item.submission_id] || ''}
                              onChange={(e) =>
                                handleCategoryChange(item.submission_id, e.target.value)
                              }
                              disabled={sortingId === item.submission_id}
                            >
                              <option value="">Select category…</option>
                              {ISSUE_CATEGORIES.map((cat) => (
                                <option key={cat} value={cat}>
                                  {cat.replace(/_/g, ' ')}
                                </option>
                              ))}
                            </select>
                            <Button
                              variant="outline"
                              size="small"
                              onClick={() => handleSortToNegative(item.submission_id)}
                              disabled={sortingId === item.submission_id}
                              aria-label={`Sort ${item.customer_name} to negative`}
                            >
                              Sort to Negative
                            </Button>
                          </div>
                          <Button
                            variant="outline"
                            size="small"
                            onClick={() => handleSortToPositive(item.submission_id)}
                            disabled={sortingId === item.submission_id}
                            aria-label={`Sort ${item.customer_name} to positive`}
                          >
                            Sort to Positive
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {(currentPage > 1 || hasMore) && (
              <nav className={styles.pagination} aria-label="Queue pagination">
                <Button
                  variant="outline"
                  size="small"
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage <= 1}
                  aria-label="Previous page"
                >
                  Previous
                </Button>
                <span>
                  Page {currentPage}
                </span>
                <Button
                  variant="outline"
                  size="small"
                  onClick={() => goToPage(currentPage + 1)}
                  disabled={!hasMore}
                  aria-label="Next page"
                >
                  Next
                </Button>
              </nav>
            )}
          </>
        )}
      </div>
    </AdminLayout>
  )
}
