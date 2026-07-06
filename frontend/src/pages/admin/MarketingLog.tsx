import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../../context/AuthContext'
import { getMarketing, ApiError, type MarketingListResponse, type MarketingEntry } from '../../api/client'
import AdminLayout from '../../components/layout/AdminLayout/AdminLayout'
import Button from '../../components/ui/Button/Button'
import styles from './admin.module.css'

const PAGE_SIZE = 20

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

function statusLabel(entry: MarketingEntry): string {
  if (entry.social_status === 'shared') return 'shared'
  if (entry.social_status === 'generation_failed') return 'generation_failed'
  return 'internal_only'
}

export default function MarketingLog() {
  const { token } = useAuth()
  const [data, setData] = useState<MarketingListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)

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
          <p>No positive submissions logged yet.</p>
        </div>
      </AdminLayout>
    )
  }

  return (
    <AdminLayout>
      <div className={`marketing-log ${styles.page}`}>
        <h1>Marketing Log</h1>

        <div className={styles.tableWrapper}>
          <table className={styles.table} aria-label="Positive submissions marketing log">
            <thead>
              <tr>
                <th>Customer Name</th>
                <th>Praise</th>
                <th>Timestamp</th>
                <th>Sharing Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((entry) => (
                <tr key={entry.submission_id}>
                  <td>{entry.customer_name}</td>
                  <td>{entry.praise_text}</td>
                  <td>{formatDate(entry.logged_at)}</td>
                  <td>{statusLabel(entry)}</td>
                </tr>
              ))}
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
