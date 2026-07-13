import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getReviewList, submitTriage, ApiError, type FeedbackRow } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import Badge from '../../components/ui/Badge/Badge'
import SourceBadge from '../../components/nlp/SourceBadge'
import SeverityBadge from '../../components/nlp/SeverityBadge'
import SortHeader from '../../components/ui/SortHeader'
import { useSort, type SortGetter } from '../../hooks/useSort'
import styles from './admin.module.css'

const PAGE_SIZE = 10
const PREVIEW_LENGTH = 140

// Module-level so the sort memo stays stable across renders.
const REVIEW_SORT: Record<string, SortGetter<FeedbackRow>> = {
  feedback_id: (r) => r.feedback_id,
  sentiment: (r) => r.sentiment,
  severity: (r) => r.severity,
  department: (r) => r.department,
}

const SENTIMENT_COLORS: Record<
  'positive' | 'neutral' | 'negative',
  'success' | 'warning' | 'error'
> = {
  positive: 'success',
  neutral: 'warning',
  negative: 'error',
}

function preview(text: string): string {
  if (text.length <= PREVIEW_LENGTH) return text
  return `${text.slice(0, PREVIEW_LENGTH).trimEnd()}…`
}

export default function ReviewQueue() {
  const { token } = useAuth()
  const [items, setItems] = useState<FeedbackRow[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [triagingId, setTriagingId] = useState<string | null>(null)
  const [triageError, setTriageError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  // Initialize search + filters + sort from the URL so views are shareable.
  const paramSentiment = searchParams.get('sentiment')
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [sentimentFilter, setSentimentFilter] = useState<string>(
    paramSentiment && ['negative', 'neutral', 'positive'].includes(paramSentiment)
      ? paramSentiment
      : 'all'
  )
  const paramSort = searchParams.get('sort')
  const initialSortKey = paramSort && REVIEW_SORT[paramSort] ? paramSort : null
  const initialSortDir = searchParams.get('dir') === 'desc' ? 'desc' : 'asc'

  const fetchReview = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const rows = await getReviewList(token, PAGE_SIZE, offset)
      setItems(rows)
      setHasMore(rows.length === PAGE_SIZE)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load review queue: ${err.message}`)
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [token, offset])

  useEffect(() => {
    fetchReview()
  }, [fetchReview])

  async function handleTriage(
    feedbackId: string,
    outcome: 'action_required' | 'no_action'
  ) {
    if (!token) return
    setTriagingId(feedbackId)
    setTriageError(null)
    try {
      await submitTriage(token, feedbackId, { outcome })
      // The row drops off the review queue once needs_review flips to false.
      await fetchReview()
    } catch (err) {
      if (err instanceof ApiError) {
        setTriageError(`Action failed: ${err.message}`)
      } else {
        setTriageError('Action failed due to a network error. Please try again.')
      }
    } finally {
      setTriagingId(null)
    }
  }

  // Client-side search + filter over the currently loaded page.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return items.filter((item) => {
      if (sentimentFilter !== 'all' && item.sentiment !== sentimentFilter) {
        return false
      }
      if (!q) return true
      const haystack = [
        item.feedback_id,
        item.text,
        item.department ?? '',
        item.sentiment ?? '',
        item.platform ?? '',
        item.channel ?? '',
        item.location_city ?? '',
        item.location_state ?? '',
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(q)
    })
  }, [items, search, sentimentFilter])

  const { sorted, sortKey, sortDir, toggleSort, setSort } = useSort(
    filtered,
    REVIEW_SORT,
    initialSortKey,
    initialSortDir
  )

  const filtersActive =
    search.trim() !== '' || sentimentFilter !== 'all' || sortKey !== null

  function clearFilters() {
    setSearch('')
    setSentimentFilter('all')
    setSort(null, 'asc')
  }

  // Reflect current search/filter/sort into the URL (replace, so back button
  // isn't polluted). Defaults are omitted to keep the URL clean.
  useEffect(() => {
    const p: Record<string, string> = {}
    if (search.trim()) p.q = search.trim()
    if (sentimentFilter !== 'all') p.sentiment = sentimentFilter
    if (sortKey) {
      p.sort = sortKey
      p.dir = sortDir
    }
    setSearchParams(p, { replace: true })
  }, [search, sentimentFilter, sortKey, sortDir, setSearchParams])

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  function goToPage(page: number) {
    setOffset((page - 1) * PAGE_SIZE)
  }

  return (
    <AdminLayout>
      <div className={`review-queue ${styles.page}`}>
        <h1>Review Queue</h1>
        <p className={styles.subtitle}>Feedback awaiting review</p>

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {triageError && (
          <div className={styles.error} role="alert">
            {triageError}
          </div>
        )}

        {loading && <p aria-live="polite">Loading review queue…</p>}

        {!loading && items.length === 0 && !error && (
          <p>No feedback is awaiting review.</p>
        )}

        {!loading && items.length > 0 && (
          <>
            <div className={styles.toolbar}>
              <div className={styles.searchBox}>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="11" cy="11" r="7" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <input
                  type="search"
                  className={styles.searchInput}
                  placeholder="Search text, ID, department, location…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Search review queue"
                />
              </div>
              <select
                className={styles.filterSelect}
                value={sentimentFilter}
                onChange={(e) => setSentimentFilter(e.target.value)}
                aria-label="Filter by sentiment"
              >
                <option value="all">All sentiments</option>
                <option value="negative">Negative</option>
                <option value="neutral">Neutral</option>
                <option value="positive">Positive</option>
              </select>
              {filtersActive && (
                <button type="button" className={styles.clearBtn} onClick={clearFilters}>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                  Clear filters
                </button>
              )}
              <span className={styles.resultCount}>
                {filtered.length} of {items.length} shown
              </span>
            </div>

            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="Review queue">
                <thead>
                  <tr>
                    <SortHeader label="Feedback ID" colKey="feedback_id" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <th>Source</th>
                    <SortHeader label="Sentiment" colKey="sentiment" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <SortHeader label="Severity" colKey="severity" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <SortHeader label="Department" colKey="department" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <th>Preview</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.length === 0 && (
                    <tr>
                      <td colSpan={7} className={styles.nlpEmpty}>
                        No feedback matches your search.
                      </td>
                    </tr>
                  )}
                  {sorted.map((item) => {
                    const isBusy = triagingId === item.feedback_id
                    return (
                      <tr key={item.feedback_id}>
                        <td>
                          <Link
                            to={`/admin/feedback/${item.feedback_id}`}
                            className={styles.rowLink}
                          >
                            {item.feedback_id.slice(0, 8)}…
                          </Link>
                        </td>
                        <td>
                          <SourceBadge
                            sourceType={item.source_type}
                            platform={item.platform}
                            channel={item.channel}
                          />
                        </td>
                        <td>
                          {item.sentiment ? (
                            <Badge color={SENTIMENT_COLORS[item.sentiment]}>
                              {item.sentiment}
                            </Badge>
                          ) : (
                            <span className={styles.nlpEmpty}>—</span>
                          )}
                        </td>
                        <td>
                          <SeverityBadge
                            severity={item.severity}
                            reasoning={item.severity_reasoning}
                          />
                        </td>
                        <td>{item.department ?? <span className={styles.nlpEmpty}>—</span>}</td>
                        <td className={styles.commentCell}>{preview(item.text)}</td>
                        <td>
                          <div className={styles.actions}>
                            <Button
                              variant="primary"
                              size="small"
                              onClick={() =>
                                handleTriage(item.feedback_id, 'action_required')
                              }
                              disabled={isBusy}
                              aria-label={`Create ticket for feedback ${item.feedback_id}`}
                            >
                              Create ticket
                            </Button>
                            <Button
                              variant="outline"
                              size="small"
                              onClick={() =>
                                handleTriage(item.feedback_id, 'no_action')
                              }
                              disabled={isBusy}
                              aria-label={`Mark feedback ${item.feedback_id} as no action`}
                            >
                              No action
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {(currentPage > 1 || hasMore) && (
              <nav className={styles.pagination} aria-label="Review queue pagination">
                <Button
                  variant="outline"
                  size="small"
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage <= 1}
                  aria-label="Previous page"
                >
                  Previous
                </Button>
                <span>Page {currentPage}</span>
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
