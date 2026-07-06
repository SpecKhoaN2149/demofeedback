import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getTickets, advanceTicket, ApiError, type Ticket } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import styles from './admin.module.css'

export default function TicketList() {
  const { token } = useAuth()
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [advancingId, setAdvancingId] = useState<string | null>(null)
  const [advanceError, setAdvanceError] = useState<string | null>(null)

  const fetchTickets = useCallback(async () => {
    if (!token) return
    setError(null)
    try {
      const data = await getTickets(token)
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
      const updated = await advanceTicket(token, ticketId)
      setTickets((prev) =>
        prev
          .map((t) => (t.id === ticketId ? updated : t))
          .filter((t) => t.status === 'open' || t.status === 'in_progress')
      )
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

  function getNextStatus(status: Ticket['status']): string {
    if (status === 'open') return 'in_progress'
    if (status === 'in_progress') return 'resolved'
    return ''
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleString()
  }

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
          <div className={styles.tableWrapper}>
            <table className={styles.table} aria-label="Tickets list">
              <thead>
                <tr>
                  <th>Ticket ID</th>
                  <th>Submission ID</th>
                  <th>Category</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((ticket) => (
                  <tr key={ticket.id}>
                    <td>{ticket.id}</td>
                    <td>
                      <Link
                        to={`/admin/submissions/${ticket.submission_id}`}
                        className={styles.rowLink}
                      >
                        {ticket.submission_id}
                      </Link>
                    </td>
                    <td>{ticket.issue_category}</td>
                    <td>{ticket.priority}</td>
                    <td>{ticket.status}</td>
                    <td>{formatDate(ticket.created_at)}</td>
                    <td>
                      <Button
                        variant="outline"
                        size="small"
                        onClick={() => handleAdvance(ticket.id)}
                        disabled={advancingId === ticket.id}
                        aria-label={`Advance ticket ${ticket.id} to ${getNextStatus(ticket.status)}`}
                      >
                        {advancingId === ticket.id
                          ? 'Advancing…'
                          : `→ ${getNextStatus(ticket.status)}`}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AdminLayout>
  )
}
