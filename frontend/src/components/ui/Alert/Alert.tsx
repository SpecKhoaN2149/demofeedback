import React from 'react'
import styles from './Alert.module.css'

export interface AlertProps {
  /** Severity of the alert, which controls color, icon, and ARIA role. */
  severity: 'success' | 'warning' | 'error' | 'info'
  /** Message content rendered inside the alert. */
  children: React.ReactNode
  /** When provided, renders a close button that invokes this callback. */
  onClose?: () => void
  /** Additional class name(s) merged onto the alert container. */
  className?: string
}

const severityClassMap: Record<AlertProps['severity'], string> = {
  success: styles.success,
  warning: styles.warning,
  error: styles.error,
  info: styles.info,
}

/**
 * Severity → ARIA role mapping. Error and warning are assertive ("alert"),
 * while success and info are polite status messages ("status").
 */
const roleMap: Record<AlertProps['severity'], 'alert' | 'status'> = {
  success: 'status',
  warning: 'alert',
  error: 'alert',
  info: 'status',
}

/**
 * Per-severity icon. Icons provide a non-color signal so that status is not
 * conveyed by color alone (dual-channel signaling).
 */
const SeverityIcon: React.FC<{ severity: AlertProps['severity'] }> = ({
  severity,
}) => {
  switch (severity) {
    case 'success':
      return (
        <svg
          className={styles.icon}
          viewBox="0 0 20 20"
          width="20"
          height="20"
          fill="currentColor"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M10 1.667A8.333 8.333 0 1 0 10 18.333 8.333 8.333 0 0 0 10 1.667Zm3.923 6.09-4.583 4.584a.833.833 0 0 1-1.179 0L5.994 10.35a.833.833 0 1 1 1.179-1.178l1.577 1.577 3.994-3.994a.833.833 0 1 1 1.179 1.178Z" />
        </svg>
      )
    case 'warning':
      return (
        <svg
          className={styles.icon}
          viewBox="0 0 20 20"
          width="20"
          height="20"
          fill="currentColor"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M18.28 15.4 11.44 3.6a1.667 1.667 0 0 0-2.88 0L1.72 15.4A1.667 1.667 0 0 0 3.16 17.9h13.68a1.667 1.667 0 0 0 1.44-2.5ZM9.167 7.5a.833.833 0 0 1 1.666 0v3.333a.833.833 0 0 1-1.666 0V7.5ZM10 15.417a1.042 1.042 0 1 1 0-2.084 1.042 1.042 0 0 1 0 2.084Z" />
        </svg>
      )
    case 'error':
      return (
        <svg
          className={styles.icon}
          viewBox="0 0 20 20"
          width="20"
          height="20"
          fill="currentColor"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M10 1.667A8.333 8.333 0 1 0 10 18.333 8.333 8.333 0 0 0 10 1.667Zm0 12.708a1.042 1.042 0 1 1 0-2.083 1.042 1.042 0 0 1 0 2.083Zm.833-4.792a.833.833 0 0 1-1.666 0V5.833a.833.833 0 0 1 1.666 0v3.75Z" />
        </svg>
      )
    case 'info':
    default:
      return (
        <svg
          className={styles.icon}
          viewBox="0 0 20 20"
          width="20"
          height="20"
          fill="currentColor"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M10 1.667A8.333 8.333 0 1 0 10 18.333 8.333 8.333 0 0 0 10 1.667Zm-.833 5a.833.833 0 0 1 1.666 0v.417a.833.833 0 0 1-1.666 0V6.667Zm2.083 7.5H8.75a.833.833 0 0 1 0-1.667h.417V10H8.75a.833.833 0 1 1 0-1.667h1.25a.833.833 0 0 1 .833.834v3.333h.417a.833.833 0 0 1 0 1.667Z" />
        </svg>
      )
  }
}

/**
 * Branded Spectrum alert used for status and feedback messages.
 *
 * - A 4px left border and a light background tint are applied per severity.
 * - `role="alert"` is used for error/warning; `role="status"` for success/info.
 * - An optional close button (X icon) is rendered when `onClose` is provided,
 *   labelled `aria-label="Close alert"`.
 */
const Alert: React.FC<AlertProps> = ({
  severity,
  children,
  onClose,
  className,
}) => {
  const classes = [styles.alert, severityClassMap[severity], className ?? '']
    .filter(Boolean)
    .join(' ')

  return (
    <div className={classes} role={roleMap[severity]}>
      <SeverityIcon severity={severity} />
      <div className={styles.content}>{children}</div>
      {onClose && (
        <button
          type="button"
          className={styles.close}
          aria-label="Close alert"
          onClick={onClose}
        >
          <svg
            viewBox="0 0 20 20"
            width="16"
            height="16"
            fill="currentColor"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M11.178 10 15.09 6.09a.833.833 0 1 0-1.179-1.178L10 8.822 6.09 4.911A.833.833 0 0 0 4.911 6.09L8.822 10l-3.911 3.911a.833.833 0 1 0 1.178 1.178L10 11.178l3.911 3.911a.833.833 0 0 0 1.178-1.178L11.178 10Z" />
          </svg>
        </button>
      )}
    </div>
  )
}

Alert.displayName = 'Alert'

export default Alert
