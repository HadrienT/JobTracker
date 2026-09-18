import type { CSSProperties } from 'react'
import type { PostingOut, Reason } from '@/mocks/contract'
import { cn } from '@/shared/lib/cn'
import { Age } from '@/shared/ui/age'
import { Deadline } from '@/shared/ui/deadline'
import { LocationCell } from '@/shared/ui/location-cell'
import { Money } from '@/shared/ui/money'
import { Score } from '@/shared/ui/score'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/ui/tooltip'
import { VisaBadge } from '@/shared/ui/visa-badge'

const STALE_AFTER_DAYS = 30

const SENIORITY_LABEL: Record<PostingOut['seniority'], string> = {
  intern: 'intern',
  graduate: 'graduate',
  junior: 'junior',
  mid: 'mid',
  senior: 'senior',
  lead: 'lead',
  unknown: 'unknown',
}

function meta(posting: PostingOut): string {
  const parts = [SENIORITY_LABEL[posting.seniority]]
  if (posting.min_years !== null) parts.push(`${String(posting.min_years)}y+`)
  if (posting.tech.length > 0) parts.push(posting.tech.slice(0, 3).join(' '))
  return parts.join(' · ')
}

const GRID_COLUMNS =
  'grid-cols-[56px_minmax(0,1fr)_40px_140px_170px_180px_110px_100px_44px_96px_32px]'

interface PostingRowProps {
  posting: PostingOut
  reasons: Reason[]
  selected: boolean
  style: CSSProperties
  onSelect: () => void
  onOpen: () => void
  onToggleFavorite: () => void
}

/** One row per posting — the single most-read element of the product (blueprint/12-WEB-UI.md §3). */
export function PostingRow({ posting, reasons, selected, style, onSelect, onOpen, onToggleFavorite }: PostingRowProps) {
  return (
    <div
      id={`posting-row-${posting.posting_id}`}
      role="option"
      aria-selected={selected}
      data-testid="posting-row"
      style={style}
      className={cn(
        'grid cursor-pointer items-center gap-3 border-b border-border px-3 text-sm',
        GRID_COLUMNS,
        selected ? 'bg-surface-elevated' : 'hover:bg-surface-elevated/60',
      )}
      onClick={onSelect}
      onDoubleClick={onOpen}
    >
      <Score score={posting.score} tier={posting.tier} reasons={reasons} />

      <Tooltip>
        <TooltipTrigger asChild>
          <span className="truncate text-text-primary">{posting.title}</span>
        </TooltipTrigger>
        <TooltipContent>{posting.title_raw}</TooltipContent>
      </Tooltip>

      <span className="text-xs text-text-tertiary">{posting.alias_count > 0 ? `+${String(posting.alias_count)}` : null}</span>

      <Tooltip>
        <TooltipTrigger asChild>
          <span className="truncate text-text-secondary">{posting.company_name}</span>
        </TooltipTrigger>
        <TooltipContent>{posting.sector}</TooltipContent>
      </Tooltip>

      <LocationCell locations={posting.locations} />

      <span className="truncate text-xs text-text-tertiary">{meta(posting)}</span>

      <VisaBadge status={posting.visa_sponsorship} />

      <Money
        amountMin={posting.compensation.amount_min}
        amountMax={posting.compensation.amount_max}
        currency={posting.compensation.currency}
        period={posting.compensation.period}
      />

      <Age postedAt={posting.posted_at} firstSeenAt={posting.first_seen_at} staleAfterDays={STALE_AFTER_DAYS} />

      <Deadline closesAt={posting.closes_at} />

      <button
        type="button"
        aria-pressed={posting.favorited}
        aria-label={posting.favorited ? 'unmark favorite' : 'mark favorite'}
        className={cn('text-base leading-none', posting.favorited ? 'text-tier-stretch' : 'text-text-tertiary')}
        onClick={(event) => {
          event.stopPropagation()
          onToggleFavorite()
        }}
      >
        {posting.favorited ? '★' : '☆'}
      </button>
    </div>
  )
}
