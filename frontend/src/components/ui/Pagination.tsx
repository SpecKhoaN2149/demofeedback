import Button from './Button/Button'
import styles from './Pagination.module.css'

interface PaginationProps {
  page: number
  totalPages: number
  onChange: (page: number) => void
  /** Total item count (for the "Showing a–b of n" summary). */
  total?: number
  from?: number
  to?: number
}

/**
 * Compact Prev/Next pager with a page indicator and an optional range summary.
 * Hidden entirely when there's only one page.
 */
export default function Pagination({ page, totalPages, onChange, total, from, to }: PaginationProps) {
  if (totalPages <= 1) return null
  return (
    <nav className={styles.pagination} aria-label="Pagination">
      {total != null && from != null && to != null && (
        <span className={styles.summary}>
          Showing {from}–{to} of {total}
        </span>
      )}
      <div className={styles.controls}>
        <Button
          variant="outline"
          size="small"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          ← Prev
        </Button>
        <span className={styles.pageIndicator}>
          Page {page} of {totalPages}
        </span>
        <Button
          variant="outline"
          size="small"
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
        >
          Next →
        </Button>
      </div>
    </nav>
  )
}
