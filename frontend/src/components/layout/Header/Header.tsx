import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import SpectrumLogo from '../../brand/SpectrumLogo/SpectrumLogo'
import styles from './Header.module.css'

export interface HeaderNavLink {
  /** Visible label for the navigation link. */
  label: string
  /** Route path the link navigates to. */
  path: string
}

export interface HeaderProps {
  /** Additional class name(s) merged onto the header element. */
  className?: string
}

/**
 * Primary navigation links rendered in the header.
 *
 * Paths map to routes defined in App.tsx. "Track Status" points at the status
 * route base and "Admin" points at the admin entry point.
 */
export const HEADER_NAV_LINKS: HeaderNavLink[] = [
  { label: 'Home', path: '/' },
  { label: 'Track Status', path: '/status' },
  { label: 'Admin', path: '/admin/dashboard' },
]

/**
 * Navigation_Shell header.
 *
 * - Fixed-position bar with a Spectrum Dark Navy background and a subtle
 *   box-shadow separating it from page content (Requirements 2.1, 2.5, 2.6).
 * - Spectrum wordmark (light variant) aligned left; horizontal navigation
 *   links centered and visible on viewports 768px and wider (Requirement 2.1).
 * - A mobile menu toggle button visible on viewports narrower than 768px that
 *   opens a slide-out navigation panel via a translateX transition
 *   (Requirements 2.1, 2.4).
 * - The mobile menu closes on ESC key press or overlay click, returning focus
 *   to the toggle button (accessibility recovery for the mobile menu).
 */
const Header: React.FC<HeaderProps> = ({ className }) => {
  const [menuOpen, setMenuOpen] = useState(false)
  const toggleRef = useRef<HTMLButtonElement>(null)

  const closeMenu = useCallback(() => {
    setMenuOpen(false)
    // Return focus to the toggle button after closing.
    toggleRef.current?.focus()
  }, [])

  // Close the mobile menu when the ESC key is pressed.
  useEffect(() => {
    if (!menuOpen) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeMenu()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [menuOpen, closeMenu])

  const classes = [styles.header, className ?? ''].filter(Boolean).join(' ')

  const navLinks = (onClick?: () => void) =>
    HEADER_NAV_LINKS.map((link) => (
      <li key={link.path}>
        <NavLink
          to={link.path}
          onClick={onClick}
          className={({ isActive }) =>
            [styles.link, isActive ? styles.active : ''].filter(Boolean).join(' ')
          }
        >
          {link.label}
        </NavLink>
      </li>
    ))

  return (
    <header className={classes}>
      <div className={styles.inner}>
        <Link to="/" className={styles.logoLink} aria-label="Spectrum home">
          <SpectrumLogo variant="light" className={styles.logo} />
        </Link>

        {/* Desktop navigation (visible >= 768px) */}
        <nav className={styles.desktopNav} aria-label="Primary">
          <ul className={styles.navList}>{navLinks()}</ul>
        </nav>

        {/* Mobile toggle button (visible < 768px) */}
        <button
          ref={toggleRef}
          type="button"
          className={styles.toggle}
          aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
          aria-expanded={menuOpen}
          aria-controls="mobile-navigation"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className={styles.toggleBar} aria-hidden="true" />
          <span className={styles.toggleBar} aria-hidden="true" />
          <span className={styles.toggleBar} aria-hidden="true" />
        </button>
      </div>

      {/* Overlay: clicking it closes the mobile menu */}
      {menuOpen && (
        <div
          className={styles.overlay}
          data-testid="mobile-menu-overlay"
          onClick={closeMenu}
          aria-hidden="true"
        />
      )}

      {/* Mobile slide-out navigation panel */}
      <nav
        id="mobile-navigation"
        className={[styles.mobileNav, menuOpen ? styles.mobileNavOpen : '']
          .filter(Boolean)
          .join(' ')}
        aria-label="Mobile"
        aria-hidden={!menuOpen}
      >
        <ul className={styles.mobileNavList}>{navLinks(closeMenu)}</ul>
      </nav>
    </header>
  )
}

Header.displayName = 'Header'

export default Header
