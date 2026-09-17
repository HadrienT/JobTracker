import type { VisaStatus } from '@/mocks/contract'
import { Badge } from '@/shared/ui/badge'

const RENDER: Record<VisaStatus, { tone: 'visaSponsors' | 'visaUnknown' | 'visaNo'; glyph: string; label: string }> = {
  sponsors: { tone: 'visaSponsors', glyph: '✓', label: 'sponsors' },
  no: { tone: 'visaNo', glyph: '✗', label: 'no visa' },
  unknown: { tone: 'visaUnknown', glyph: '?', label: 'visa' },
}

interface VisaBadgeProps {
  status: VisaStatus
}

/** Three distinct renders, each with a glyph *and* a label — never color alone. */
export function VisaBadge({ status }: VisaBadgeProps) {
  const { tone, glyph, label } = RENDER[status]
  return (
    <Badge tone={tone} data-testid="visa-badge" data-visa-status={status}>
      <span aria-hidden="true">{glyph}</span>
      <span>{label}</span>
    </Badge>
  )
}
