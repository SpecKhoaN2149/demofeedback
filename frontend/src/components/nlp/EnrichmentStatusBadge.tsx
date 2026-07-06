import Badge from '../ui/Badge/Badge'

export type EnrichmentStatus = 'pending' | 'completed' | 'failed' | 'timeout'

const STATUS_CONFIG: Record<
  EnrichmentStatus,
  { color: 'success' | 'warning' | 'error' | 'info' | 'neutral'; label: string }
> = {
  completed: { color: 'success', label: 'Analyzed' },
  pending: { color: 'info', label: 'Analyzing…' },
  failed: { color: 'error', label: 'Analysis failed' },
  timeout: { color: 'warning', label: 'Analysis timed out' },
}

export interface EnrichmentStatusBadgeProps {
  status?: EnrichmentStatus | string | null
  className?: string
}

/**
 * Compact badge communicating the NLP enrichment state of a submission.
 * Falls back to a neutral "Unknown" badge for unrecognized states.
 */
export default function EnrichmentStatusBadge({
  status,
  className,
}: EnrichmentStatusBadgeProps) {
  const config =
    (status && STATUS_CONFIG[status as EnrichmentStatus]) || {
      color: 'neutral' as const,
      label: 'Unknown',
    }

  return (
    <Badge color={config.color} className={className}>
      {config.label}
    </Badge>
  )
}
