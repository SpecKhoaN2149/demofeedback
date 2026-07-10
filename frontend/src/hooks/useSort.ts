import { useState, useMemo } from 'react'

export type SortDir = 'asc' | 'desc'

/** Value extractor for a sortable column. Return null/undefined to sort last. */
export type SortGetter<T> = (row: T) => string | number | null | undefined

/**
 * Generic client-side table sorting.
 *
 * Pass the rows and a map of column-key → value getter. `getters` should be a
 * stable (module-level or memoized) object so the sort memo isn't invalidated
 * every render. Nullish values always sort to the end regardless of direction;
 * strings compare with locale-aware numeric ordering.
 */
export function useSort<T>(
  rows: T[],
  getters: Record<string, SortGetter<T>>,
  initialKey: string | null = null,
  initialDir: SortDir = 'asc'
) {
  const [sortKey, setSortKey] = useState<string | null>(initialKey)
  const [sortDir, setSortDir] = useState<SortDir>(initialDir)

  const sorted = useMemo(() => {
    if (!sortKey || !getters[sortKey]) return rows
    const get = getters[sortKey]
    const copy = [...rows]
    copy.sort((a, b) => {
      const va = get(a)
      const vb = get(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      let cmp: number
      if (typeof va === 'number' && typeof vb === 'number') {
        cmp = va - vb
      } else {
        cmp = String(va).localeCompare(String(vb), undefined, { numeric: true })
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return copy
  }, [rows, sortKey, sortDir, getters])

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  /** Imperatively set the sort key/direction (e.g. to reset to a default). */
  function setSort(key: string | null, dir: SortDir = 'asc') {
    setSortKey(key)
    setSortDir(dir)
  }

  return { sorted, sortKey, sortDir, toggleSort, setSort }
}
