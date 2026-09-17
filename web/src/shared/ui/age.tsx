import { displayedPostingDate, formatAge } from '@/shared/lib/dates'
import { cn } from '@/shared/lib/cn'

interface AgeProps {
  postedAt: string | null
  firstSeenAt: string
  staleAfterDays: number
  now?: Date
}

/** `3d`, `2w`, `47d` — orange past half of `staleAfterDays`. */
export function Age({ postedAt, firstSeenAt, staleAfterDays, now }: AgeProps) {
  const date = displayedPostingDate(postedAt, firstSeenAt)
  const { text, stale } = formatAge(date, staleAfterDays, now)
  return (
    <span
      className={cn('font-tabular', stale ? 'text-warning' : 'text-text-secondary')}
      title={date.toISOString().slice(0, 10)}
    >
      {text}
    </span>
  )
}
