import React from 'react'
import Header from '../Header/Header'
import Footer from '../Footer/Footer'
import styles from './NavigationShell.module.css'

export interface NavigationShellProps {
  /** Page content rendered within the main landmark. */
  children: React.ReactNode
  /** Optional additional className applied to the shell container. */
  className?: string
}

/**
 * Navigation_Shell layout.
 *
 * The persistent page structure that wraps all page content. It composes the
 * fixed-position Header and the Footer around a centered main content area.
 *
 * - CSS Grid with `grid-template-rows: auto 1fr auto` establishes a
 *   full-height header / main / footer layout (Requirement 2.1, 2.3).
 * - The main content area is constrained to a maximum width of 1200px, centered
 *   horizontally, with 16px horizontal padding on mobile and 32px on desktop
 *   (Requirement 2.2).
 * - Because the Header is fixed-position, the main area applies a top padding
 *   offset (~64px) so page content is not obscured by the header (Requirement
 *   2.1).
 */
const NavigationShell: React.FC<NavigationShellProps> = ({
  children,
  className,
}) => {
  const classes = [styles.shell, className ?? ''].filter(Boolean).join(' ')

  return (
    <div className={classes}>
      <Header />
      <main className={styles.main}>
        <div className={styles.content}>{children}</div>
      </main>
      <Footer />
    </div>
  )
}

NavigationShell.displayName = 'NavigationShell'

export default NavigationShell
