import { useState, useMemo, useEffect } from 'react'

/**
 * Client-side pagination over an in-memory list.
 *
 * Returns the current page's slice plus page state/among helpers. The page is
 * clamped when the list shrinks (e.g. after filtering). Callers should reset to
 * page 1 when their filter/sort inputs change.
 */
export function usePagination<T>(items: T[], pageSize = 20) {
  const [page, setPage] = useState(1)
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize))

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const start = (page - 1) * pageSize
  const pageItems = useMemo(
    () => items.slice(start, start + pageSize),
    [items, start, pageSize]
  )

  return {
    page,
    setPage,
    totalPages,
    pageItems,
    pageSize,
    total: items.length,
    /** 1-based index of the first item shown on this page (0 when empty). */
    from: items.length === 0 ? 0 : start + 1,
    /** 1-based index of the last item shown on this page. */
    to: Math.min(start + pageSize, items.length),
  }
}
