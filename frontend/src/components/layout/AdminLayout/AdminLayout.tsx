import React from 'react'
import AdminSidebar from '../AdminSidebar/AdminSidebar'
import AdminTopBar from '../AdminTopBar/AdminTopBar'
import styles from './AdminLayout.module.css'

export interface AdminLayoutProps {
  /** Admin page content rendered in the main content column. */
  children: React.ReactNode
  /** Additional class name(s) merged onto the layout container. */
  className?: string
}

/**
 * Layout shell for admin pages.
 *
 * Composes the {@link AdminSidebar} with a content area and adapts responsively
 * (Requirements 11.1, 11.2):
 *
 * - Desktop (>= 1024px): a CSS grid with a fixed 240px sidebar column and a
 *   flexible content column.
 * - Tablet and below (< 1024px): the grid collapses to a single column and the
 *   sidebar becomes a horizontal, scrollable tab bar rendered below the header,
 *   with its nav links reflowing horizontally.
 */
const AdminLayout: React.FC<AdminLayoutProps> = ({ children, className }) => {
  const classes = [styles.wrapper, className ?? ''].filter(Boolean).join(' ')

  return (
    <div className={classes}>
      <AdminTopBar />
      <div className={styles.layout}>
        <AdminSidebar className={styles.sidebar} />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  )
}

AdminLayout.displayName = 'AdminLayout'

export default AdminLayout
