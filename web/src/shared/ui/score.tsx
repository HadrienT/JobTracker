import type { Reason, Tier } from '@/mocks/contract'
import { cn } from '@/shared/lib/cn'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/ui/tooltip'

const TIER_DOT: Record<Tier, string> = {
  strong: 'bg-tier-strong',
  possible: 'bg-tier-possible',
  stretch: 'bg-tier-stretch',
  rejected: 'bg-tier-rejected',
}

const TIER_LABEL: Record<Tier, string> = {
  strong: 'strong',
  possible: 'possible',
  stretch: 'stretch',
  rejected: 'rejected',
}

interface ScoreProps {
  score: number
  tier: Tier
  reasons: Reason[]
}

/** Tabular score + tier pastille. Hover reveals the `Reason`s that produced it. */
export function Score({ score, tier, reasons }: ScoreProps) {
  const body = (
    <span className="inline-flex items-center gap-1.5">
      <span
        role="img"
        className={cn('inline-block h-2 w-2 rounded-full', TIER_DOT[tier])}
        aria-label={TIER_LABEL[tier]}
      />
      <span className="font-tabular font-semibold text-text-primary">{score}</span>
    </span>
  )

  if (reasons.length === 0) return body

  return (
    <Tooltip>
      <TooltipTrigger asChild>{body}</TooltipTrigger>
      <TooltipContent>
        <ul className="flex flex-col gap-1">
          {reasons.map((reason) => (
            <li key={reason.code} className="flex items-baseline gap-2 text-xs">
              <span className={cn('font-tabular', reason.delta >= 0 ? 'text-tier-strong' : 'text-danger')}>
                {reason.delta >= 0 ? '+' : ''}
                {reason.delta}
              </span>
              <span className="text-text-secondary">{reason.code}</span>
            </li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  )
}
