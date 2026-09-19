import { useMemo, type UIEvent } from 'react'
import { usePinPostings, type PostingsFilter } from '@/api/queries'
import { postingMeta } from '@/features/feed/posting-meta'
import { Score } from '@/shared/ui/score'
import { VisaBadge } from '@/shared/ui/visa-badge'

export interface Place {
  country: string
  city: string
}

interface PinListPanelProps {
  filter: PostingsFilter
  place: Place
  /** What the pin claims to hold — shown before the list has loaded, and checked against it in tests. */
  count: number
  onOpenPosting: (postingId: string) => void
  onClose: () => void
}

const NEAR_BOTTOM_PX = 240

/**
 * The postings behind a pin that holds several. A side drawer, not a modal: the map stays live
 * so another pin can be picked without closing this one first. Choosing a posting opens the
 * usual detail panel on top; closing that lands back here.
 */
export function PinListPanel({ filter, place, count, onOpenPosting, onClose }: PinListPanelProps) {
  const query = usePinPostings(filter, place)
  const items = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data])
  const title = `${place.city}, ${place.country}`

  function onScroll(event: UIEvent<HTMLUListElement>) {
    const el = event.currentTarget
    if (query.hasNextPage && !query.isFetchingNextPage && el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX) {
      void query.fetchNextPage()
    }
  }

  return (
    <aside
      aria-label={`Postings in ${title}`}
      className="flex w-96 shrink-0 flex-col border-l border-border bg-surface"
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
          <p className="text-xs text-text-secondary">
            {String(count)} {count === 1 ? 'posting' : 'postings'}, best match first
          </p>
        </div>
        <button
          type="button"
          aria-label="Close list"
          className="rounded-md border border-border px-2 py-1 text-text-secondary hover:bg-surface-elevated"
          onClick={onClose}
        >
          ✕
        </button>
      </header>

      {query.isPending && <p className="p-4 text-sm text-text-tertiary">Loading…</p>}
      {query.isError && (
        <div className="flex flex-col items-start gap-2 p-4 text-sm text-text-secondary">
          <span>Couldn&apos;t load these postings.</span>
          <button
            type="button"
            className="rounded-md border border-border px-2 py-1 text-text-primary hover:bg-surface-elevated"
            onClick={() => void query.refetch()}
          >
            Retry
          </button>
        </div>
      )}

      {query.isSuccess && items.length === 0 && (
        <p className="p-4 text-sm text-text-secondary">No posting here matches the current filters.</p>
      )}

      {items.length > 0 && (
        <ul aria-label="Postings" className="flex-1 overflow-y-auto" onScroll={onScroll}>
          {items.map((posting) => (
            <li key={posting.posting_id} className="border-b border-border">
              <button
                type="button"
                className="flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-surface-elevated"
                onClick={() => {
                  onOpenPosting(posting.posting_id)
                }}
              >
                <span className="flex items-center justify-between gap-3">
                  <Score score={posting.score} tier={posting.tier} reasons={[]} />
                  <VisaBadge status={posting.visa_sponsorship} />
                </span>
                <span className="text-sm font-medium text-text-primary">{posting.title}</span>
                <span className="text-xs text-text-secondary">{posting.company_name}</span>
                <span className="text-xs text-text-tertiary">{postingMeta(posting)}</span>
              </button>
            </li>
          ))}
          {query.hasNextPage && (
            <li className="p-3 text-center">
              <button
                type="button"
                disabled={query.isFetchingNextPage}
                className="rounded-md border border-border px-3 py-1 text-xs text-text-secondary hover:bg-surface-elevated disabled:opacity-50"
                onClick={() => void query.fetchNextPage()}
              >
                {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </button>
            </li>
          )}
        </ul>
      )}
    </aside>
  )
}
