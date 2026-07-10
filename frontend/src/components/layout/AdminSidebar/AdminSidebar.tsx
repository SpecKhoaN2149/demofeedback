import React from 'react'
import { NavLink } from 'react-router-dom'
import styles from './AdminSidebar.module.css'

export interface AdminNavLink {
  /** Visible label for the navigation link. */
  label: string
  /** Route path the link navigates to. */
  path: string
  /** Inline SVG icon shown beside (or in place of) the label. */
  icon: React.ReactNode
}

export interface AdminSidebarProps {
  /** Additional class name(s) merged onto the sidebar element. */
  className?: string
  /** When true, the sidebar renders as a narrow icon-only rail (desktop). */
  collapsed?: boolean
  /** Toggles the collapsed state. */
  onToggle?: () => void
  /** Optional count badges keyed by nav path (e.g. { '/admin/queue': 5 }). */
  badges?: Record<string, number>
}

// Small, dependency-free line icons (currentColor so they inherit link color).
const icon = {
  dashboard: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" />
      <rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" />
    </svg>
  ),
  queue: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  ),
  tickets: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 5h16a1 1 0 0 1 1 1v3a2 2 0 0 0 0 4v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3a2 2 0 0 0 0-4V6a1 1 0 0 1 1-1z" />
      <line x1="12" y1="5" x2="12" y2="19" strokeDasharray="2 3" />
    </svg>
  ),
  marketing: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 11l18-5v12L3 14v-3z" /><path d="M11.6 16.8a3 3 0 0 1-5.8-1.6" />
    </svg>
  ),
  trends: (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="3 17 9 11 13 15 21 7" /><polyline points="14 7 21 7 21 14" />
    </svg>
  ),
}

/**
 * Admin navigation links, matching the admin routes defined in App.tsx.
 */
export const ADMIN_NAV_LINKS: AdminNavLink[] = [
  { label: 'Dashboard', path: '/admin/dashboard', icon: icon.dashboard },
  { label: 'Review Queue', path: '/admin/queue', icon: icon.queue },
  { label: 'Tickets', path: '/admin/tickets', icon: icon.tickets },
  { label: 'Marketing Log', path: '/admin/marketing', icon: icon.marketing },
  { label: 'Trend Analysis', path: '/admin/trends', icon: icon.trends },
]

/**
 * Sidebar navigation for the admin panel.
 *
 * - Collapsible between a full 240px rail (icon + label) and a narrow 64px
 *   icon-only rail; the active link is highlighted with a soft tint and an
 *   inset accent bar.
 * - When collapsed, labels are hidden and each link exposes a native tooltip
 *   (title) plus an aria-label so it stays accessible.
 */
const AdminSidebar: React.FC<AdminSidebarProps> = ({
  className,
  collapsed = false,
  onToggle,
  badges = {},
}) => {
  const classes = [styles.sidebar, collapsed ? styles.collapsed : '', className ?? '']
    .filter(Boolean)
    .join(' ')

  return (
    <nav className={classes} aria-label="Admin navigation">
      <button
        type="button"
        className={styles.toggle}
        onClick={onToggle}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-expanded={!collapsed}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {collapsed ? (
            <polyline points="9 6 15 12 9 18" />
          ) : (
            <polyline points="15 6 9 12 15 18" />
          )}
        </svg>
      </button>

      <ul className={styles.list}>
        {ADMIN_NAV_LINKS.map((link) => {
          const badge = badges[link.path] ?? 0
          const badgeLabel = badge > 99 ? '99+' : String(badge)
          return (
            <li key={link.path}>
              <NavLink
                to={link.path}
                title={collapsed ? link.label : undefined}
                aria-label={
                  badge > 0 ? `${link.label} (${badge} awaiting review)` : link.label
                }
                className={({ isActive }) =>
                  [styles.link, isActive ? styles.active : ''].filter(Boolean).join(' ')
                }
              >
                <span className={styles.icon}>
                  {link.icon}
                  {/* In the collapsed rail the label is hidden, so show a small
                      dot indicator on the icon instead of the numeric pill. */}
                  {badge > 0 && collapsed && <span className={styles.badgeDot} aria-hidden="true" />}
                </span>
                <span className={styles.label}>{link.label}</span>
                {badge > 0 && !collapsed && (
                  <span className={styles.badge} aria-hidden="true">{badgeLabel}</span>
                )}
              </NavLink>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

AdminSidebar.displayName = 'AdminSidebar'

export default AdminSidebar
