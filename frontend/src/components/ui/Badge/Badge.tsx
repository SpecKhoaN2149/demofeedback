import React from 'react'
import styles from './Badge.module.css'

export interface BadgeProps {
  /** Semantic color of the badge, mapping to a Spectrum design token. */
  color: 'success' | 'warning' | 'error' | 'info' | 'neutral'
  /** Content rendered inside the badge. */
  children: React.ReactNode
  /** Additional class name(s) merged onto the badge element. */
  className?: string
}

const colorClassMap: Record<BadgeProps['color'], string> = {
  success: styles.success,
  warning: styles.warning,
  error: styles.error,
  info: styles.info,
  neutral: styles.neutral,
}

/**
 * Branded Spectrum badge used for compact status labels.
 *
 * - Rounded pill shape (radius-full).
 * - 4px vertical / 8px horizontal padding, xs font-size, font-weight 600.
 * - Each color maps to its semantic design token: the light variant background
 *   paired with the semantic color text for good contrast.
 */
const Badge: React.FC<BadgeProps> = ({ color, children, className }) => {
  const classes = [styles.badge, colorClassMap[color], className ?? '']
    .filter(Boolean)
    .join(' ')

  return <span className={classes}>{children}</span>
}

Badge.displayName = 'Badge'

export default Badge
