import React from 'react'
import { NavLink } from 'react-router-dom'
import styles from './AdminSidebar.module.css'

export interface AdminNavLink {
  /** Visible label for the navigation link. */
  label: string
  /** Route path the link navigates to. */
  path: string
}

export interface AdminSidebarProps {
  /** Additional class name(s) merged onto the sidebar element. */
  className?: string
}

/**
 * Admin navigation links, matching the admin routes defined in App.tsx.
 */
export const ADMIN_NAV_LINKS: AdminNavLink[] = [
  { label: 'Dashboard', path: '/admin/dashboard' },
  { label: 'Review Queue', path: '/admin/queue' },
  { label: 'Tickets', path: '/admin/tickets' },
  { label: 'Marketing Log', path: '/admin/marketing' },
  { label: 'Trend Analysis', path: '/admin/trends' },
]

/**
 * Sidebar navigation for the admin panel.
 *
 * - Fixed 240px width on desktop (Requirement 11.1).
 * - Renders links to Dashboard, Review Queue, Tickets, Marketing Log, and
 *   Trend Analysis using react-router-dom's NavLink.
 * - The active link is highlighted with a Spectrum Blue background and white
 *   text via the `active` module class applied through NavLink's className
 *   callback.
 */
const AdminSidebar: React.FC<AdminSidebarProps> = ({ className }) => {
  const classes = [styles.sidebar, className ?? ''].filter(Boolean).join(' ')

  return (
    <nav className={classes} aria-label="Admin navigation">
      <ul className={styles.list}>
        {ADMIN_NAV_LINKS.map((link) => (
          <li key={link.path}>
            <NavLink
              to={link.path}
              className={({ isActive }) =>
                [styles.link, isActive ? styles.active : ''].filter(Boolean).join(' ')
              }
            >
              {link.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

AdminSidebar.displayName = 'AdminSidebar'

export default AdminSidebar
