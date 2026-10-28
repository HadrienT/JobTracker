import type { PostingsFilter } from '@/api/queries'
import { type FeedView, feedViewOf, STATUS_OPTIONS, VIEW_TIERS } from '@/features/filters/defaults'
import { FEED_VIEWS } from '@/features/feed/triage'
import { cn } from '@/shared/lib/cn'

interface TriageTabsProps {
  filter: PostingsFilter
  onChange: (patch: Partial<PostingsFilter>) => void
}

/**
 * "Applied" is the status filter with something in it — the panel's own Status control narrows it.
 * Each tab comes with its own tiers; a rejection reason only means something under Filtered out.
 */
function patchFor(view: FeedView): Partial<PostingsFilter> {
  return {
    triage: view === 'maybe' || view === 'no' ? view : null,
    statuses: view === 'applied' ? STATUS_OPTIONS.map((option) => option.value) : [],
    tiers: VIEW_TIERS[view],
    rejection_reasons: [],
  }
}

/** Inbox / Maybe / No / Applied / Filtered out — which list the feed is showing. The filters apply to whichever is picked. */
export function TriageTabs({ filter, onChange }: TriageTabsProps) {
  const view = feedViewOf(filter)
  return (
    <div role="tablist" aria-label="Feed lists" className="flex w-max rounded-md border border-border text-sm">
      {FEED_VIEWS.map((option) => {
        const active = option.value === view
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            className={cn(
              'whitespace-nowrap px-3 py-1.5 first:rounded-l-md last:rounded-r-md md:py-1',
              active ? 'bg-surface-elevated text-text-primary' : 'text-text-secondary hover:text-text-primary',
            )}
            onClick={() => {
              onChange(patchFor(option.value))
            }}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
