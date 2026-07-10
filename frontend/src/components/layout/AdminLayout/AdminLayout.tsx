import React, { useEffect, useState } from 'react'
import AdminSidebar from '../AdminSidebar/AdminSidebar'
import AdminTopBar from '../AdminTopBar/AdminTopBar'
import { useAuth } from '../../../context/AuthContext'
import { getReviewCount } from '../../../api/client'
import styles from './AdminLayout.module.css'

export interface AdminLayoutProps {
  /** Admin page content rendered in the main content column. */
  children: React.ReactNode
  /** Additional class name(s) merged onto the layout container. */
  className?: string
}

const COLLAPSE_KEY = 'admin.sidebar.collapsed'

/**
 * Layout shell for admin pages.
 *
 * Composes the {@link AdminSidebar} with a content area and adapts responsively
 * (Requirements 11.1, 11.2):
 *
 * - Desktop (>= 1024px): a CSS grid with a sidebar column and a flexible
 *   content column. The sidebar can be collapsed to an icon rail; the grid
 *   column narrows accordingly so every admin page reflows to use the space.
 *   The collapsed preference is persisted to localStorage.
 * - Tablet and below (< 1024px): the grid collapses to a single column and the
 *   sidebar becomes a horizontal, scrollable tab bar rendered below the header.
 */
const AdminLayout: React.FC<AdminLayoutProps> = ({ children, className }) => {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(COLLAPSE_KEY) === 'true'
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, String(collapsed))
    } catch {
      // Ignore storage failures (private mode, quota) — state still works.
    }
  }, [collapsed])

  // Review-queue badge count. Refetched on each admin page mount so it stays
  // reasonably fresh as feedback is reviewed.
  const { token } = useAuth()
  const [reviewCount, setReviewCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!token) return
    getReviewCount(token)
      .then((r) => {
        if (!cancelled) setReviewCount(r.count)
      })
      .catch(() => {
        /* Badge is best-effort; ignore failures. */
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const classes = [styles.wrapper, className ?? ''].filter(Boolean).join(' ')
  const layoutClasses = [styles.layout, collapsed ? styles.collapsed : '']
    .filter(Boolean)
    .join(' ')

  return (
    <div className={classes}>
      <AdminTopBar />
      <div className={layoutClasses}>
        <AdminSidebar
          className={styles.sidebar}
          collapsed={collapsed}
          onToggle={() => setCollapsed((c) => !c)}
          badges={{ '/admin/queue': reviewCount }}
        />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  )
}

AdminLayout.displayName = 'AdminLayout'

export default AdminLayout
