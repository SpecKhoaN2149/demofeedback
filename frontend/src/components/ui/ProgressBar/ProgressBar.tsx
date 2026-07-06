import React from 'react'
import styles from './ProgressBar.module.css'

export interface ProgressBarProps {
  /** Current progress percentage. Clamped to the [0, 100] range. */
  value: number
  /** Height variant of the bar. Defaults to 'default' (8px). */
  size?: 'small' | 'default' | 'large'
  /** When true, applies a repeating opacity pulse to the fill. */
  pulsing?: boolean
  /** Optional text label rendered above the track. */
  label?: string
  /** Additional class names applied to the wrapper element. */
  className?: string
}

const sizeClassMap: Record<NonNullable<ProgressBarProps['size']>, string> = {
  small: styles.small,
  default: styles.default,
  large: styles.large,
}

/**
 * Branded Spectrum progress bar.
 *
 * - Track uses the neutral-200 token; the fill uses Spectrum Blue and animates
 *   its width using the normal transition duration.
 * - `value` is clamped into the [0, 100] range so out-of-range inputs never
 *   overflow the track.
 * - When `value` reaches 100 the fill switches to the success color.
 * - `pulsing` applies a repeating opacity animation to signal an in-progress
 *   state.
 * - Exposes progressbar ARIA semantics (role, aria-valuenow/min/max).
 */
const ProgressBar: React.FC<ProgressBarProps> = ({
  value,
  size = 'default',
  pulsing = false,
  label,
  className,
}) => {
  const clampedValue = Math.min(100, Math.max(0, value))
  const isComplete = clampedValue === 100

  const trackClasses = [styles.track, sizeClassMap[size]]
    .filter(Boolean)
    .join(' ')

  const fillClasses = [
    styles.fill,
    isComplete ? styles.complete : '',
    pulsing ? styles.pulsing : '',
  ]
    .filter(Boolean)
    .join(' ')

  const wrapperClasses = [styles.wrapper, className ?? '']
    .filter(Boolean)
    .join(' ')

  return (
    <div className={wrapperClasses}>
      {label ? <span className={styles.label}>{label}</span> : null}
      <div
        className={trackClasses}
        role="progressbar"
        aria-valuenow={clampedValue}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div className={fillClasses} style={{ width: `${clampedValue}%` }} />
      </div>
    </div>
  )
}

ProgressBar.displayName = 'ProgressBar'

export default ProgressBar
