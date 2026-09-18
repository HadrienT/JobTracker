import { useVirtualizer } from '@tanstack/react-virtual'
import { type RefObject, useEffect, useMemo, useRef, useState } from 'react'
import { type PostingsFilter, type SortKey, useSetFavorite, useSetHidden, usePostingsFeed } from '@/api/queries'
import { PostingRow } from '@/features/feed/posting-row'
import { useFeedKeyboardShortcuts } from '@/features/feed/use-keyboard-shortcuts'
import { useToast } from '@/features/favorites/use-toast'

const ROW_HEIGHT = 44
const PREFETCH_ROWS_FROM_END = 10
const OVERSCAN = 8

interface FeedListProps {
  filter: PostingsFilter
  sort: SortKey
  searchInputRef: RefObject<HTMLInputElement | null>
  isPanelOpen: boolean
  hasActiveFilters: boolean
  onOpenPosting: (id: string) => void
}

/** The product screen: a keyset-paginated, keyboard-driven, virtualized list of postings. */
export function FeedList({ filter, sort, searchInputRef, isPanelOpen, hasActiveFilters, onOpenPosting }: FeedListProps) {
  const query = usePostingsFeed(filter, sort)
  const setFavorite = useSetFavorite()
  const setHidden = useSetHidden()
  const toast = useToast()
  const parentRef = useRef<HTMLDivElement>(null)
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  function toggleFavorite(postingId: string, value: boolean) {
    setFavorite.mutate(
      { postingId, value },
      {
        onError: () => {
          toast.show('Could not update favorite — try again.')
        },
      },
    )
  }

  function hidePosting(postingId: string) {
    setHidden.mutate(
      { postingId, value: true },
      {
        onSuccess: () => {
          toast.show('Posting hidden.', {
            label: 'Undo',
            onClick: () => {
              // Un-hiding can't be spliced back into the cache from nothing — the
              // item's data is gone from it the moment it's filtered out. A refetch
              // is what actually brings it back, same as the server would after a reload.
              setHidden.mutate({ postingId, value: false }, { onSuccess: () => void query.refetch() })
            },
          })
        },
        onError: () => {
          toast.show('Could not hide this posting — try again.')
        },
      },
    )
  }

  const items = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data])

  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: OVERSCAN,
  })

  useEffect(() => {
    setSelectedIndex((current) => {
      if (current === null) return null
      return current > items.length - 1 ? (items.length > 0 ? items.length - 1 : null) : current
    })
  }, [items.length])

  const virtualItems = rowVirtualizer.getVirtualItems()

  useEffect(() => {
    const last = virtualItems.at(-1)
    if (last === undefined) return
    if (last.index >= items.length - PREFETCH_ROWS_FROM_END && query.hasNextPage && !query.isFetchingNextPage) {
      void query.fetchNextPage()
    }
    // query itself is a fresh object each render; only its data-bearing fields matter here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [virtualItems, items.length, query.hasNextPage, query.isFetchingNextPage])

  function moveSelection(delta: number) {
    if (items.length === 0) return
    setSelectedIndex((current) => {
      const next = current === null ? (delta > 0 ? 0 : items.length - 1) : Math.min(Math.max(current + delta, 0), items.length - 1)
      rowVirtualizer.scrollToIndex(next, { align: 'auto' })
      return next
    })
  }

  const selected = selectedIndex !== null ? items[selectedIndex] : undefined

  useFeedKeyboardShortcuts(
    {
      onNext: () => {
        moveSelection(1)
      },
      onPrev: () => {
        moveSelection(-1)
      },
      onOpen: () => {
        if (selected) onOpenPosting(selected.posting_id)
      },
      onOpenSource: () => {
        if (selected) window.open(selected.url, '_blank', 'noopener,noreferrer')
      },
      onToggleFavorite: () => {
        if (selected) toggleFavorite(selected.posting_id, !selected.favorited)
      },
      onHide: () => {
        if (selected) hidePosting(selected.posting_id)
      },
      onFocusSearch: () => {
        searchInputRef.current?.focus()
      },
      onEscape: () => {
        setSelectedIndex(null)
      },
    },
    !isPanelOpen,
  )

  if (query.isPending) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-text-tertiary">Loading postings…</div>
    )
  }

  // `isLoadingError` (no data at all) is distinct from a failed *next*-page fetch
  // (`isFetchNextPageError`, handled below): the latter must leave pages 1..N
  // on screen, per blueprint/wp/WP10-web-feed.md §6.
  if (query.isLoadingError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-sm text-text-secondary">
        <p>Couldn&apos;t load postings: {query.error.message}</p>
        <button
          type="button"
          className="rounded-md border border-border px-3 py-1.5 text-text-primary hover:bg-surface-elevated"
          onClick={() => void query.refetch()}
        >
          Retry
        </button>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-text-secondary" data-testid="feed-empty">
        {hasActiveFilters ? 'No postings match this filter.' : 'No postings have been collected yet.'}
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div
        ref={parentRef}
        role="listbox"
        aria-label="Job postings"
        aria-activedescendant={selected ? `posting-row-${selected.posting_id}` : undefined}
        className="flex-1 overflow-y-auto"
      >
        <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', width: '100%' }}>
          {virtualItems.map((virtualRow) => {
            const posting = items[virtualRow.index]
            if (!posting) return null
            return (
              <PostingRow
                key={posting.posting_id}
                posting={posting}
                // PostingOut (the list row) carries score and tier but not the Reason
                // trail — that only comes back from the detail endpoint, so the
                // score hover in the feed is dot+number only; full reasons live in
                // the detail panel (blueprint/12-WEB-UI.md §5).
                reasons={[]}
                selected={virtualRow.index === selectedIndex}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: virtualRow.size,
                  transform: `translateY(${String(virtualRow.start)}px)`,
                }}
                onSelect={() => {
                  setSelectedIndex(virtualRow.index)
                }}
                onOpen={() => {
                  onOpenPosting(posting.posting_id)
                }}
                onToggleFavorite={() => {
                  toggleFavorite(posting.posting_id, !posting.favorited)
                }}
              />
            )
          })}
        </div>
      </div>
      {query.isFetchNextPageError && (
        <div className="flex items-center justify-center gap-3 border-t border-border bg-surface py-2 text-sm text-text-secondary">
          <span>Couldn&apos;t load more postings.</span>
          <button
            type="button"
            className="rounded-md border border-border px-2 py-1 text-text-primary hover:bg-surface-elevated"
            onClick={() => void query.fetchNextPage()}
          >
            Retry
          </button>
        </div>
      )}
    </div>
  )
}
