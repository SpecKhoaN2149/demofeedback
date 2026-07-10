import type { SortDir } from '../../hooks/useSort'
import styles from './SortHeader.module.css'

interface SortHeaderProps {
  /** Visible column label. */
  label: string
  /** Column key this header sorts by (matches a key in the getters map). */
  colKey: string
  /** Currently active sort key. */
  sortKey: string | null
  /** Current sort direction. */
  sortDir: SortDir
  /** Toggle handler from useSort. */
  onSort: (key: string) => void
  /** Optional extra class (e.g. numeric alignment) merged onto the th. */
  className?: string
}

/**
 * A sortable table header cell: a full-width button that toggles sorting and
 * shows an indicator (▲/▼ when active, a neutral ⇅ otherwise).
 */
export default function SortHeader({
  label,
  colKey,
  sortKey,
  sortDir,
  onSort,
  className,
}: SortHeaderProps) {
  const active = sortKey === colKey
  const thClasses = [styles.th, className ?? ''].filter(Boolean).join(' ')
  return (
    <th className={thClasses} aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className={styles.btn} onClick={() => onSort(colKey)}>
        <span>{label}</span>
        <span className={`${styles.arrow} ${active ? styles.active : ''}`} aria-hidden="true">
          {active ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
        </span>
      </button>
    </th>
  )
}
