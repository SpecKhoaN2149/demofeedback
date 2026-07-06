import React from 'react'
import styles from './Button.module.css'

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style of the button. Defaults to 'primary'. */
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost'
  /** Size of the button. Defaults to 'medium'. */
  size?: 'small' | 'medium' | 'large'
  /** When true, the button expands to fill the width of its container. */
  fullWidth?: boolean
  children: React.ReactNode
}

const variantClassMap: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary: styles.primary,
  secondary: styles.secondary,
  outline: styles.outline,
  ghost: styles.ghost,
}

const sizeClassMap: Record<NonNullable<ButtonProps['size']>, string> = {
  small: styles.small,
  medium: styles.medium,
  large: styles.large,
}

/**
 * Branded Spectrum button with variant, size, and full-width options.
 *
 * - Hover darkens the background via `filter: brightness(0.9)`.
 * - Keyboard focus shows a 2px Spectrum Blue ring with a 2px offset.
 * - The disabled state reduces opacity, shows a not-allowed cursor, and
 *   disables pointer events so click handlers do not fire.
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'medium',
      fullWidth = false,
      className,
      type = 'button',
      children,
      ...rest
    },
    ref
  ) => {
    const classes = [
      styles.button,
      variantClassMap[variant],
      sizeClassMap[size],
      fullWidth ? styles.fullWidth : '',
      className ?? '',
    ]
      .filter(Boolean)
      .join(' ')

    return (
      <button ref={ref} type={type} className={classes} {...rest}>
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'

export default Button
