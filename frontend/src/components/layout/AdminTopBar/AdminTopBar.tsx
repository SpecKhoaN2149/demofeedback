import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import SpectrumLogo from '../../brand/SpectrumLogo/SpectrumLogo'
import Button from '../../ui/Button/Button'
import { useAuth } from '../../../context/AuthContext'
import styles from './AdminTopBar.module.css'

export interface AdminTopBarProps {
  /** Additional class name(s) merged onto the top bar element. */
  className?: string
}

/**
 * Top bar for the admin panel.
 *
 * Provides the two navigation paths the admin area was previously missing:
 * - The Spectrum wordmark links back to the public site home (`/`).
 * - A Logout button clears the session and returns to the admin login page.
 *
 * The logged-in username is shown for context when available.
 */
const AdminTopBar: React.FC<AdminTopBarProps> = ({ className }) => {
  const { username, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/admin/login', { replace: true })
  }

  const classes = [styles.bar, className ?? ''].filter(Boolean).join(' ')

  return (
    <header className={classes}>
      <div className={styles.inner}>
        <Link to="/" className={styles.logoLink} aria-label="Spectrum home">
          <SpectrumLogo variant="light" className={styles.logo} />
          <span className={styles.badge}>Admin</span>
        </Link>

        <div className={styles.right}>
          {username && (
            <span className={styles.user}>
              Signed in as <strong>{username}</strong>
            </span>
          )}
          <Button variant="outline" size="small" onClick={handleLogout} className={styles.logout}>
            Log out
          </Button>
        </div>
      </div>
    </header>
  )
}

AdminTopBar.displayName = 'AdminTopBar'

export default AdminTopBar
