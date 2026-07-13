import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import {
  getMarketing,
  ApiError,
  type MarketingListResponse,
  type MarketingEntry,
} from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import SortHeader from '../../components/ui/SortHeader'
import { useSort, type SortGetter } from '../../hooks/useSort'
import { sourceDisplay } from '../../utils/sourceDisplay'
import { extractMentionedNames } from '../../utils/mentionedNames'
import styles from './admin.module.css'

const PAGE_SIZE = 10

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Render feedback text with any mentioned person names highlighted inline. */
function renderWithMentions(text: string, names: string[]) {
  if (names.length === 0) return text
  const re = new RegExp(`(${names.map(escapeRegExp).join('|')})`, 'g')
  const lookup = new Set(names)
  return text.split(re).map((part, i) =>
    lookup.has(part) ? (
      <mark key={i} className={styles.mentionMark}>{part}</mark>
    ) : (
      part
    )
  )
}

// Module-level so the sort memo stays stable across renders.
const MARKETING_SORT: Record<string, SortGetter<MarketingEntry>> = {
  text: (e) => e.text,
  source: (e) => e.platform ?? e.source_type,
  created_at: (e) => e.created_at,
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

export default function MarketingLog() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [data, setData] = useState<MarketingListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [mentionsOnly, setMentionsOnly] = useState(searchParams.get('mentions') === '1')
  const paramSort = searchParams.get('sort')
  const initialSortKey =
    paramSort && MARKETING_SORT[paramSort] ? paramSort : 'created_at'
  const initialSortDir = searchParams.get('dir') === 'asc' ? 'asc' : 'desc'

  const fetchMarketing = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)

    try {
      const response = await getMarketing(token, PAGE_SIZE, offset)
      setData(response)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load marketing log: ${err.message}`)
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [token, offset])

  useEffect(() => {
    fetchMarketing()
  }, [fetchMarketing])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  const filteredItems = useMemo(() => {
    if (!data) return []
    const q = search.trim().toLowerCase()
    return data.items.filter((e) => {
      if (mentionsOnly && extractMentionedNames(e.text).length === 0) return false
      if (!q) return true
      return [e.text, e.source_type, e.platform ?? ''].join(' ').toLowerCase().includes(q)
    })
  }, [data, search, mentionsOnly])

  const { sorted, sortKey, sortDir, toggleSort, setSort } = useSort(
    filteredItems,
    MARKETING_SORT,
    initialSortKey,
    initialSortDir
  )

  const filtersActive =
    search.trim() !== '' || mentionsOnly || sortKey !== 'created_at' || sortDir !== 'desc'

  function clearFilters() {
    setSearch('')
    setMentionsOnly(false)
    setSort('created_at', 'desc')
  }

  // Persist search/mentions/sort to the URL (replace) for shareable views.
  useEffect(() => {
    const p: Record<string, string> = {}
    if (search.trim()) p.q = search.trim()
    if (mentionsOnly) p.mentions = '1'
    if (sortKey) {
      p.sort = sortKey
      p.dir = sortDir
    }
    setSearchParams(p, { replace: true })
  }, [search, mentionsOnly, sortKey, sortDir, setSearchParams])

  function goToPage(page: number) {
    setOffset((page - 1) * PAGE_SIZE)
  }

  if (loading) {
    return (
      <AdminLayout>
        <div className={`marketing-log ${styles.page}`}>
          <h1>Marketing Log</h1>
          <p>Loading marketing log…</p>
        </div>
      </AdminLayout>
    )
  }

  if (error) {
    return (
      <AdminLayout>
        <div className={`marketing-log ${styles.page}`}>
          <h1>Marketing Log</h1>
          <div className={styles.error} role="alert">{error}</div>
          <Button variant="outline" size="small" onClick={fetchMarketing}>Retry</Button>
        </div>
      </AdminLayout>
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <AdminLayout>
        <div className={`marketing-log ${styles.page}`}>
          <h1>Marketing Log</h1>
          <p className={styles.subtitle}>Positive feedback, suitable for marketing</p>
          <p>No positive feedback logged yet.</p>
        </div>
      </AdminLayout>
    )
  }

  return (
    <AdminLayout>
      <div className={`marketing-log ${styles.page}`}>
        <h1>Marketing Log</h1>
        <p className={styles.subtitle}>Positive feedback, suitable for marketing</p>

        <div className={styles.toolbar}>
          <div className={styles.searchBox}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              className={styles.searchInput}
              placeholder="Search feedback text or source…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search marketing log"
            />
          </div>
          <label className={styles.filterToggle}>
            <input
              type="checkbox"
              checked={mentionsOnly}
              onChange={(e) => setMentionsOnly(e.target.checked)}
            />
            Mentions a person
          </label>
          {filtersActive && (
            <button type="button" className={styles.clearBtn} onClick={clearFilters}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
              Clear filters
            </button>
          )}
          <span className={styles.resultCount}>
            {filteredItems.length} of {data.items.length} shown
          </span>
        </div>

        <div className={styles.tableWrapper}>
          <table className={styles.table} aria-label="Positive feedback marketing log">
            <thead>
              <tr>
                <SortHeader label="Feedback" colKey="text" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader label="Source" colKey="source" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader label="Timestamp" colKey="created_at" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th>Original</th>
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={4} className={styles.nlpEmpty}>
                    No feedback matches your search.
                  </td>
                </tr>
              )}
              {sorted.map((entry) => {
                const src = sourceDisplay(entry)
                const names = extractMentionedNames(entry.text)
                return (
                  <tr
                    key={entry.feedback_id}
                    className={styles.clickableRow}
                    onClick={() => navigate(`/admin/feedback/${entry.feedback_id}`)}
                  >
                    <td className={styles.commentCell}>{renderWithMentions(entry.text, names)}</td>
                    <td>
                      {src.label}
                      {src.detail ? ` · ${src.detail}` : ''}
                    </td>
                    <td>{formatDate(entry.created_at)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <Link className={styles.rowLink} to={`/admin/feedback/${entry.feedback_id}`}>
                        View feedback →
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <nav className={styles.pagination} aria-label="Marketing log pagination">
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
              Page {currentPage} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="small"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
              aria-label="Next page"
            >
              Next
            </Button>
          </nav>
        )}
      </div>
    </AdminLayout>
  )
}
