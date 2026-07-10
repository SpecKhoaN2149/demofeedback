import styles from './SourceBadge.module.css'

export interface SourceBadgeProps {
  sourceType: 'direct' | 'social'
  platform?: 'reddit' | 'x' | 'facebook' | null
  channel?: string | null
  /** Hide the text label and show the logo only (for tight table cells). */
  iconOnly?: boolean
}

/** Small inline brand logos so the source is recognizable at a glance. */
function PlatformIcon({ platform }: { platform: string | null | undefined }) {
  switch (platform) {
    case 'x':
      return (
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <rect width="24" height="24" rx="5" fill="#000000" />
          <path
            fill="#ffffff"
            d="M17.3 5h1.9l-4.2 4.8L20 19h-3.9l-3-3.9L9.6 19H7.7l4.5-5.1L6 5h4l2.7 3.6L15.6 5h1.7zm-.7 12.8h1L9.5 6.1H8.4l8.2 11.7z"
          />
        </svg>
      )
    case 'reddit':
      return (
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <circle cx="12" cy="12" r="12" fill="#FF4500" />
          <circle cx="12" cy="13.5" r="6.2" fill="#ffffff" />
          <circle cx="18.4" cy="7.2" r="1.5" fill="#ffffff" />
          <circle cx="9.4" cy="12.6" r="1.05" fill="#FF4500" />
          <circle cx="14.6" cy="12.6" r="1.05" fill="#FF4500" />
          <path
            d="M9.3 15.4c1.5 1.1 3.9 1.1 5.4 0"
            stroke="#FF4500"
            strokeWidth="0.9"
            strokeLinecap="round"
            fill="none"
          />
          <path
            d="M12 7.9l.9-3.1 2.8.7"
            stroke="#ffffff"
            strokeWidth="0.9"
            strokeLinecap="round"
            fill="none"
          />
        </svg>
      )
    case 'facebook':
      return (
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <rect width="24" height="24" rx="5" fill="#1877F2" />
          <path
            fill="#ffffff"
            d="M15.3 12.3l.4-2.6h-2.5V8c0-.72.35-1.42 1.48-1.42h1.13V4.35S14.79 4.2 13.85 4.2c-1.96 0-3.24 1.19-3.24 3.34v1.9H8.3v2.6h2.31V19h2.84v-6.7h2.05z"
          />
        </svg>
      )
    default:
      // Direct / web-form globe.
      return (
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="none" stroke="#0059B8" strokeWidth="1.6" />
          <path
            d="M2.5 12h19M12 2.5c3 3 3 16 0 19M12 2.5c-3 3-3 16 0 19"
            fill="none"
            stroke="#0059B8"
            strokeWidth="1.4"
          />
        </svg>
      )
  }
}

const PLATFORM_LABEL: Record<string, string> = {
  x: 'X',
  reddit: 'Reddit',
  facebook: 'Facebook',
}

/**
 * Renders a source chip with the originating platform's logo (X / Reddit /
 * Facebook) for social feedback, or a globe + channel label for direct
 * submissions. Missing platform on a social record shows just the label.
 */
export default function SourceBadge({
  sourceType,
  platform,
  channel,
  iconOnly = false,
}: SourceBadgeProps) {
  const isSocial = sourceType === 'social'
  const label = isSocial
    ? PLATFORM_LABEL[platform ?? ''] ?? 'Social'
    : channel === 'web_form'
      ? 'Web'
      : channel ?? 'Direct'

  return (
    <span className={styles.badge} title={label}>
      <PlatformIcon platform={isSocial ? (platform ?? null) : 'web'} />
      {!iconOnly && <span className={styles.label}>{label}</span>}
    </span>
  )
}
