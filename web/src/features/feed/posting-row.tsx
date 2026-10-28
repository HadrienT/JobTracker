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
import { postingMeta } from '@/features/feed/posting-meta'
import { isNewSinceLastVisit } from '@/features/feed/last-visit'
import { StatusBadge } from '@/features/feed/status-badge'
import { rejectionReasonLabel } from '@/features/filters/defaults'
import { TRIAGE_ACTIONS, type TriageView } from '@/features/feed/triage'

const STALE_AFTER_DAYS = 30

const GRID_COLUMNS =
  'grid-cols-[52px_minmax(220px,1fr)_28px_112px_140px_120px_96px_112px_44px_56px_88px]'

interface PostingRowProps {
  posting: PostingOut
  reasons: Reason[]
  selected: boolean
  /** A phone: two stacked lines instead of eleven columns. */
  compact?: boolean
  style: CSSProperties
  onSelect: () => void
  onOpen: () => void
  onToggleFavorite: () => void
  onTriage: (to: TriageView) => void
}

/** One row per posting — the single most-read element of the product (blueprint/12-WEB-UI.md §3). */
export function PostingRow({
  posting,
  reasons,
  selected,
  compact = false,
  style,
  onSelect,
  onOpen,
  onToggleFavorite,
  onTriage,
}: PostingRowProps) {
  // A `grid`/`row` rather than a listbox/option: the favorite toggle is a real button, and
  // an `option` may not contain one (axe `nested-interactive`, `aria-required-children`).
  // A row may hold any number of cells, so the data columns are one cell and the toggle
  // another, and `aria-activedescendant` on the grid still drives the keyboard selection.
  const title = (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex min-w-0 items-center gap-2">
          {isNewSinceLastVisit(posting.first_seen_at) && (
            <span
              aria-label="New since your last visit"
              title="New since your last visit"
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-tier-possible"
            />
          )}
          <span className="truncate text-text-primary">{posting.title}</span>
          {posting.application_status !== null && <StatusBadge status={posting.application_status} />}
          {posting.rejection_reason !== null && (
            <span className="shrink-0 rounded-full border border-tier-rejected/60 px-1.5 py-0.5 text-[10px] font-medium leading-none text-tier-rejected">
              {rejectionReasonLabel(posting.rejection_reason)}
            </span>
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent>{posting.title_raw}</TooltipContent>
    </Tooltip>
  )

  return (
    <div
      id={`posting-row-${posting.posting_id}`}
      role="row"
      aria-selected={selected}
      data-testid="posting-row"
      style={style}
      className={cn(
        'relative cursor-pointer border-b border-border',
        selected ? 'bg-surface-elevated' : 'hover:bg-surface-elevated/60',
      )}
      onClick={() => {
        onSelect()
        onOpen()
      }}
    >
      {compact ? (
        <div role="gridcell" className="flex h-full flex-col justify-center gap-1.5 px-3 text-sm">
          {/* Right padding: the triage and favorite buttons sit over the end of the first line. */}
          <div className="flex min-w-0 items-center gap-2 pr-28">
            <Score score={posting.score} tier={posting.tier} reasons={reasons} />
            {title}
          </div>
          <div className="flex min-w-0 items-center gap-2 overflow-hidden whitespace-nowrap text-xs">
            <span className="max-w-[45%] shrink-0 truncate text-text-secondary">{posting.company_name}</span>
            <span className="min-w-0 truncate">
              <LocationCell locations={posting.locations} />
            </span>
            <VisaBadge status={posting.visa_sponsorship} />
            <span className="shrink-0">
              <Money
                amountMin={posting.compensation.amount_min}
                amountMax={posting.compensation.amount_max}
                currency={posting.compensation.currency}
                period={posting.compensation.period}
              />
            </span>
            <span className="ml-auto shrink-0">
              <Age postedAt={posting.posted_at} firstSeenAt={posting.first_seen_at} staleAfterDays={STALE_AFTER_DAYS} />
            </span>
          </div>
        </div>
      ) : (
        <div role="gridcell" className={cn('grid h-full items-center gap-2 px-3 text-sm', GRID_COLUMNS)}>
          <Score score={posting.score} tier={posting.tier} reasons={reasons} />

          {title}

          <span className="text-xs text-text-tertiary">{posting.alias_count > 0 ? `+${String(posting.alias_count)}` : null}</span>

          <Tooltip>
            <TooltipTrigger asChild>
              <span className="truncate text-text-secondary">{posting.company_name}</span>
            </TooltipTrigger>
            <TooltipContent>{posting.sector}</TooltipContent>
          </Tooltip>

          <LocationCell locations={posting.locations} />

          <span className="truncate text-xs text-text-tertiary">{postingMeta(posting)}</span>

          <VisaBadge status={posting.visa_sponsorship} />

          <Money
            amountMin={posting.compensation.amount_min}
            amountMax={posting.compensation.amount_max}
            currency={posting.compensation.currency}
            period={posting.compensation.period}
          />

          <Age postedAt={posting.posted_at} firstSeenAt={posting.first_seen_at} staleAfterDays={STALE_AFTER_DAYS} />

          <Deadline closesAt={posting.closes_at} />

          <span aria-hidden="true" />
        </div>
      )}
      <div
        role="gridcell"
        className={cn('absolute flex items-center', compact ? 'right-1 top-1' : 'right-3 top-0 h-full')}
      >
        {TRIAGE_ACTIONS.filter((action) => action.value !== posting.triage).map((action) => (
          <button
            key={action.label}
            type="button"
            aria-label={action.label}
            title={action.label}
            className={cn('text-sm leading-none text-text-tertiary hover:text-text-primary', compact ? 'h-9 w-9' : 'h-8 w-7')}
            onClick={(event) => {
              event.stopPropagation()
              onTriage(action.value)
            }}
          >
            {action.glyph}
          </button>
        ))}
        <button
          type="button"
          aria-pressed={posting.favorited}
          aria-label={posting.favorited ? 'unmark favorite' : 'mark favorite'}
          className={cn(
            'text-base leading-none',
            compact ? 'h-9 w-9' : 'h-8 w-8',
            posting.favorited ? 'text-tier-stretch' : 'text-text-tertiary',
          )}
          onClick={(event) => {
            event.stopPropagation()
            onToggleFavorite()
          }}
        >
          {posting.favorited ? '★' : '☆'}
        </button>
      </div>
    </div>
  )
}
