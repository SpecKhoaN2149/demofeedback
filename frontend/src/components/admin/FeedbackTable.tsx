import { useEffect, useMemo, useState, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { listAdminFeedback, ApiError, type FeedbackRow } from '../../api/client'
import Badge from '../ui/Badge/Badge'
import SourceBadge from '../nlp/SourceBadge'
import SeverityBadge from '../nlp/SeverityBadge'
import SortHeader from '../ui/SortHeader'
import { useSort, type SortGetter } from '../../hooks/useSort'
import styles from '../../pages/admin/admin.module.css'

const PREVIEW_LENGTH = 120
const PAGE = 100

const SENTIMENT_COLORS: Record<
  'positive' | 'neutral' | 'negative',
  'success' | 'warning' | 'error'
> = { positive: 'success', neutral: 'warning', negative: 'error' }

const FEEDBACK_SORT: Record<string, SortGetter<FeedbackRow>> = {
  feedback_id: (r) => r.feedback_id,
  sentiment: (r) => r.sentiment,
  severity: (r) => r.severity,
  department: (r) => r.department,
  enrichment_status: (r) => r.enrichment_status,
  created_at: (r) => r.created_at,
}

function preview(text: string): string {
  if (text.length <= PREVIEW_LENGTH) return text
  return `${text.slice(0, PREVIEW_LENGTH).trimEnd()}…`
}

/**
 * Dashboard-embedded table of ALL feedback, with the same search / filter /
 * sort / clear affordances as the other admin tables. Fetches every record
 * (paginated behind the scenes) so filtering works across the whole dataset.
 */
export default function FeedbackTable() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [rows, setRows] = useState<FeedbackRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sentimentFilter, setSentimentFilter] = useState('all')
  const [departmentFilter, setDepartmentFilter] = useState('all')

  const fetchAll = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const all: FeedbackRow[] = []
      let offset = 0
      // Page through everything (cap defensively so a bug can't loop forever).
      for (let i = 0; i < 50; i++) {
        const page = await listAdminFeedback(token, PAGE, offset)
        all.push(...page)
        if (page.length < PAGE) break
        offset += PAGE
      }
      setRows(all)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load feedback: ${err.message}`)
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const departments = useMemo(() => {
    const set = new Set<string>()
    rows.forEach((r) => r.department && set.add(r.department))
    return Array.from(set).sort()
  }, [rows])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (sentimentFilter !== 'all' && r.sentiment !== sentimentFilter) return false
      if (departmentFilter !== 'all' && r.department !== departmentFilter) return false
      if (!q) return true
      return [
        r.feedback_id,
        r.text,
        r.department ?? '',
        r.sentiment ?? '',
        r.platform ?? '',
        r.channel ?? '',
        r.location_city ?? '',
        r.location_state ?? '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(q)
    })
  }, [rows, search, sentimentFilter, departmentFilter])

  const { sorted, sortKey, sortDir, toggleSort, setSort } = useSort(
    filtered,
    FEEDBACK_SORT,
    'created_at',
    'desc'
  )

  const filtersActive =
    search.trim() !== '' ||
    sentimentFilter !== 'all' ||
    departmentFilter !== 'all' ||
    sortKey !== 'created_at' ||
    sortDir !== 'desc'

  function clearFilters() {
    setSearch('')
    setSentimentFilter('all')
    setDepartmentFilter('all')
    setSort('created_at', 'desc')
  }

  if (loading) return <p>Loading feedback…</p>
  if (error) return <div className={styles.error} role="alert">{error}</div>
  if (rows.length === 0) return <p>No feedback yet.</p>

  return (
    <>
      <div className={styles.toolbar}>
        <div className={styles.searchBox}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="search"
            className={styles.searchInput}
            placeholder="Search text, ID, department, location…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search feedback"
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
        <select
          className={styles.filterSelect}
          value={departmentFilter}
          onChange={(e) => setDepartmentFilter(e.target.value)}
          aria-label="Filter by department"
        >
          <option value="all">All departments</option>
          {departments.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
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
          {filtered.length} of {rows.length} shown
        </span>
      </div>

      <div className={styles.tableWrapper}>
        <table className={styles.table} aria-label="All feedback">
          <thead>
            <tr>
              <SortHeader label="Feedback ID" colKey="feedback_id" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <th>Source</th>
              <SortHeader label="Sentiment" colKey="sentiment" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader label="Severity" colKey="severity" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader label="Department" colKey="department" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <th>Preview</th>
              <SortHeader label="Status" colKey="enrichment_status" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <th>Ticket</th>
              <SortHeader label="Created" colKey="created_at" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={9} className={styles.nlpEmpty}>No feedback matches your search.</td>
              </tr>
            )}
            {sorted.map((r) => (
              <tr
                key={r.feedback_id}
                className={styles.clickableRow}
                onClick={() => navigate(`/admin/feedback/${r.feedback_id}`)}
              >
                <td onClick={(e) => e.stopPropagation()}>
                  <Link to={`/admin/feedback/${r.feedback_id}`} className={styles.rowLink}>
                    {r.feedback_id.slice(0, 8)}…
                  </Link>
                </td>
                <td>
                  <SourceBadge sourceType={r.source_type} platform={r.platform} channel={r.channel} />
                </td>
                <td>
                  {r.sentiment ? (
                    <Badge color={SENTIMENT_COLORS[r.sentiment]}>{r.sentiment}</Badge>
                  ) : (
                    <span className={styles.nlpEmpty}>—</span>
                  )}
                </td>
                <td>
                  <SeverityBadge severity={r.severity} reasoning={r.severity_reasoning} />
                </td>
                <td>{r.department ?? <span className={styles.nlpEmpty}>—</span>}</td>
                <td className={styles.commentCell}>{preview(r.text)}</td>
                <td>{r.enrichment_status}</td>
                <td>
                  {r.ticket_id ? (
                    <Link
                      to={`/admin/tickets/${r.ticket_id}`}
                      className={styles.rowLink}
                      onClick={(e) => e.stopPropagation()}
                    >
                      View
                    </Link>
                  ) : (
                    <span className={styles.nlpEmpty}>—</span>
                  )}
                </td>
                <td>{new Date(r.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
