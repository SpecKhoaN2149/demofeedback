import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getTickets, advanceTicket, ApiError, type TicketWithCount } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import SortHeader from '../../components/ui/SortHeader'
import Pagination from '../../components/ui/Pagination'
import { useSort, type SortGetter } from '../../hooks/useSort'
import { usePagination } from '../../hooks/usePagination'
import styles from './admin.module.css'

const STATUS_PILL: Record<TicketWithCount['status'], string> = {
  open: styles.statusOpen,
  in_progress: styles.statusProgress,
  resolved: styles.statusResolved,
}

// Module-level so the sort memo stays stable across renders.
const TICKET_SORT: Record<string, SortGetter<TicketWithCount>> = {
  ticket_id: (t) => t.ticket_id,
  issue_category: (t) => t.issue_category,
  priority: (t) => t.priority,
  status: (t) => t.status,
  linked: (t) => t.linked_feedback_count,
  created_at: (t) => t.created_at,
}

export default function TicketList() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [tickets, setTickets] = useState<TicketWithCount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [advancingId, setAdvancingId] = useState<string | null>(null)
  const [advanceError, setAdvanceError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [statusFilter, setStatusFilter] = useState<string>(
    ['open', 'in_progress', 'resolved'].includes(searchParams.get('status') ?? '')
      ? (searchParams.get('status') as string)
      : 'all'
  )
  const [multiOnly, setMultiOnly] = useState(searchParams.get('multi') === '1')
  const paramSort = searchParams.get('sort')
  const initialSortKey =
    paramSort && TICKET_SORT[paramSort] ? paramSort : 'created_at'
  const initialSortDir = searchParams.get('dir') === 'desc' ? 'desc' : 'asc'

  const fetchTickets = useCallback(async () => {
    if (!token) return
    setError(null)
    try {
      // Fetch every ticket (incl. resolved); the status filter is client-side.
      const data = await getTickets(token, 'all')
      setTickets(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load tickets: ${err.message}`)
      } else {
        setError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchTickets()
  }, [fetchTickets])

  async function handleAdvance(ticketId: string) {
    if (!token) return
    setAdvanceError(null)
    setAdvancingId(ticketId)

    try {
      await advanceTicket(token, ticketId)
      await fetchTickets()
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setAdvanceError(`Invalid transition for ticket ${ticketId}: ticket cannot be advanced further.`)
        } else {
          setAdvanceError(`Failed to advance ticket ${ticketId}: ${err.message}`)
        }
      } else {
        setAdvanceError('Unable to connect to the server. Please try again.')
      }
    } finally {
      setAdvancingId(null)
    }
  }

  function getNextStatus(status: TicketWithCount['status']): string {
    if (status === 'open') return 'in_progress'
    if (status === 'in_progress') return 'resolved'
    return ''
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleString()
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return tickets.filter((t) => {
      if (statusFilter !== 'all' && t.status !== statusFilter) return false
      if (multiOnly && t.linked_feedback_count <= 1) return false
      if (!q) return true
      return [t.ticket_id, t.issue_category, t.priority, t.status]
        .join(' ')
        .toLowerCase()
        .includes(q)
    })
  }, [tickets, search, statusFilter, multiOnly])

  const { sorted, sortKey, sortDir, toggleSort, setSort } = useSort(
    filtered,
    TICKET_SORT,
    initialSortKey,
    initialSortDir
  )

  const { page, setPage, totalPages, pageItems, total, from, to } = usePagination(sorted, 10)

  // Reset to the first page whenever the filtered/sorted set changes.
  useEffect(() => {
    setPage(1)
  }, [search, statusFilter, multiOnly, sortKey, sortDir, setPage])

  const filtersActive =
    search.trim() !== '' ||
    statusFilter !== 'all' ||
    multiOnly ||
    sortKey !== 'created_at' ||
    sortDir !== 'asc'

  function clearFilters() {
    setSearch('')
    setStatusFilter('all')
    setMultiOnly(false)
    setSort('created_at', 'asc')
  }

  // Persist search/status/multi/sort to the URL (replace) for shareable views.
  useEffect(() => {
    const p: Record<string, string> = {}
    if (search.trim()) p.q = search.trim()
    if (statusFilter !== 'all') p.status = statusFilter
    if (multiOnly) p.multi = '1'
    if (sortKey) {
      p.sort = sortKey
      p.dir = sortDir
    }
    setSearchParams(p, { replace: true })
  }, [search, statusFilter, multiOnly, sortKey, sortDir, setSearchParams])

  if (loading) {
    return (
      <AdminLayout>
        <div className={`ticket-list ${styles.page}`}>
          <h1>Tickets</h1>
          <p>Loading tickets…</p>
        </div>
      </AdminLayout>
    )
  }

  if (error) {
    return (
      <AdminLayout>
        <div className={`ticket-list ${styles.page}`}>
          <h1>Tickets</h1>
          <div className={styles.error} role="alert">{error}</div>
          <Button variant="outline" size="small" onClick={fetchTickets}>Retry</Button>
        </div>
      </AdminLayout>
    )
  }

  return (
    <AdminLayout>
      <div className={`ticket-list ${styles.page}`}>
        <h1>Tickets</h1>

        {advanceError && (
          <div className={styles.error} role="alert">{advanceError}</div>
        )}

        {tickets.length === 0 ? (
          <p>No open or in-progress tickets.</p>
        ) : (
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
                  placeholder="Search ID, category, priority…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Search tickets"
                />
              </div>
              <select
                className={styles.filterSelect}
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Filter by status"
              >
                <option value="all">All statuses</option>
                <option value="open">Open</option>
                <option value="in_progress">In progress</option>
                <option value="resolved">Resolved</option>
              </select>
              <label className={styles.filterToggle}>
                <input
                  type="checkbox"
                  checked={multiOnly}
                  onChange={(e) => setMultiOnly(e.target.checked)}
                />
                Multiple feedback only
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
                {filtered.length} of {tickets.length} shown
              </span>
            </div>

            <div className={styles.tableWrapper}>
              <table className={styles.table} aria-label="Tickets list">
                <thead>
                  <tr>
                    <SortHeader label="Ticket ID" colKey="ticket_id" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <SortHeader label="Category" colKey="issue_category" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <SortHeader label="Priority" colKey="priority" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <SortHeader label="Status" colKey="status" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <SortHeader label="Linked feedback" colKey="linked" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} className={styles.numCell} />
                    <SortHeader label="Created" colKey="created_at" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.length === 0 && (
                    <tr>
                      <td colSpan={7} className={styles.nlpEmpty}>
                        No tickets match your search.
                      </td>
                    </tr>
                  )}
                  {pageItems.map((ticket) => {
                    const nextStatus = getNextStatus(ticket.status)
                    return (
                      <tr
                        key={ticket.ticket_id}
                        className={styles.clickableRow}
                        onClick={() => navigate(`/admin/tickets/${ticket.ticket_id}`)}
                      >
                        <td>
                          <Link
                            to={`/admin/tickets/${ticket.ticket_id}`}
                            className={styles.rowLink}
                            onClick={(e) => e.stopPropagation()}
                          >
                            {ticket.ticket_id.slice(0, 8)}…
                          </Link>
                        </td>
                        <td>{ticket.issue_category}</td>
                        <td>{ticket.priority}</td>
                        <td>
                          <span className={`${styles.statusPill} ${STATUS_PILL[ticket.status]}`}>
                            {ticket.status.replace('_', ' ')}
                          </span>
                        </td>
                        <td className={styles.numCell}>{ticket.linked_feedback_count}</td>
                        <td>{formatDate(ticket.created_at)}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <Button
                            variant="outline"
                            size="small"
                            onClick={() => handleAdvance(ticket.ticket_id)}
                            disabled={advancingId === ticket.ticket_id || !nextStatus}
                            aria-label={`Advance ticket ${ticket.ticket_id} to ${nextStatus}`}
                          >
                            {advancingId === ticket.ticket_id
                              ? 'Advancing…'
                              : nextStatus
                                ? `→ ${nextStatus.replace('_', ' ')}`
                                : 'Resolved'}
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <Pagination
              page={page}
              totalPages={totalPages}
              onChange={setPage}
              total={total}
              from={from}
              to={to}
            />
          </>
        )}
      </div>
    </AdminLayout>
  )
}
