import React from 'react'
import styles from './Card.module.css'

export interface CardProps {
  /** Content rendered inside the card. */
  children: React.ReactNode
  /** When true, the card is keyboard-activatable and lifts on hover. */
  interactive?: boolean
  /** When true, the card uses a 1px border instead of a shadow. */
  bordered?: boolean
  /** Additional class names to merge with the card's own classes. */
  className?: string
  /** Click handler. For interactive cards, also triggered by Enter/Space. */
  onClick?: () => void
  /** Optional keydown handler, invoked after the built-in keyboard handling. */
  onKeyDown?: (e: React.KeyboardEvent) => void
  /** Overrides the default tabIndex for interactive cards (0). */
  tabIndex?: number
  /** Accessible label, useful for interactive cards without visible text. */
  'aria-label'?: string
}

/**
 * Branded Spectrum surface container.
 *
 * - Base: white background, medium radius, medium shadow, 24px padding.
 * - Interactive: hover lifts the shadow to large and scales to 1.02, exposes a
 *   keyboard focus ring, and behaves as a button (role="button", tabIndex 0,
 *   Enter/Space activate onClick).
 * - Bordered: replaces the shadow with a 1px neutral-200 border.
 */
const Card = React.forwardRef<HTMLDivElement, CardProps>(
  (
    {
      children,
      interactive = false,
      bordered = false,
      className,
      onClick,
      onKeyDown,
      tabIndex,
      'aria-label': ariaLabel,
    },
    ref
  ) => {
    const classes = [
      styles.card,
      interactive ? styles.interactive : '',
      bordered ? styles.bordered : '',
      className ?? '',
    ]
      .filter(Boolean)
      .join(' ')

    const handleKeyDown = (e: React.KeyboardEvent) => {
      if (interactive && (e.key === 'Enter' || e.key === ' ')) {
        // Prevent the space key from scrolling the page and ensure activation
        // mirrors native button behavior.
        e.preventDefault()
        onClick?.()
      }
      onKeyDown?.(e)
    }

    const interactiveProps = interactive
      ? {
          role: 'button' as const,
          tabIndex: tabIndex ?? 0,
          onClick,
          onKeyDown: handleKeyDown,
        }
      : {
          tabIndex,
          onClick,
          onKeyDown: onKeyDown
            ? (e: React.KeyboardEvent) => onKeyDown(e)
            : undefined,
        }

    return (
      <div ref={ref} className={classes} aria-label={ariaLabel} {...interactiveProps}>
        {children}
      </div>
    )
  }
)

Card.displayName = 'Card'

export default Card
