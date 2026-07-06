import React from 'react'
import { Link } from 'react-router-dom'
import styles from './Footer.module.css'

export interface FooterProps {
  /** Optional additional className applied to the footer element. */
  className?: string
}

/**
 * Navigation_Shell footer.
 *
 * Renders the Charter Communications copyright notice with the current year
 * alongside links to the Terms of Service and Privacy Policy pages.
 *
 * Requirement 2.3: footer contains copyright text
 * "© {current year} Charter Communications, Inc." and links to Terms of
 * Service and Privacy Policy.
 */
const Footer: React.FC<FooterProps> = ({ className }) => {
  const currentYear = new Date().getFullYear()

  const classes = [styles.footer, className ?? ''].filter(Boolean).join(' ')

  return (
    <footer className={classes}>
      <p className={styles.copyright}>
        © {currentYear} Charter Communications, Inc.
      </p>
      <nav className={styles.links} aria-label="Footer">
        <Link className={styles.link} to="/terms">
          Terms of Service
        </Link>
        <Link className={styles.link} to="/privacy">
          Privacy Policy
        </Link>
      </nav>
    </footer>
  )
}

Footer.displayName = 'Footer'

export default Footer
