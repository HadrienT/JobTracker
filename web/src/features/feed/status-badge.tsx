import type { ApplicationStatus } from '@/api/queries'
import { STATUS_OPTIONS } from '@/features/filters/defaults'
import { cn } from '@/shared/lib/cn'

const TONE: Record<ApplicationStatus, string> = {
  applied: 'border-tier-possible/50 text-tier-possible',
  interview: 'border-tier-stretch/60 text-tier-stretch',
  offer: 'border-tier-strong/60 text-tier-strong',
  rejected: 'border-tier-rejected/60 text-tier-rejected',
  withdrawn: 'border-border text-text-secondary',
}

/** Where the application stands, in one word — shown next to the title so a tracked row stands out. */
export function StatusBadge({ status }: { status: ApplicationStatus }) {
  const label = STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
  return (
    <span
      className={cn('shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none', TONE[status])}
    >
      {label}
    </span>
  )
}
