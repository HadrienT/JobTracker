import { useEffect, useRef, useState } from 'react'
import type { SortKey } from '@/api/queries'
import { ActiveFilterPills } from '@/features/filters/active-filter-pills'
import { isDefaultFilter } from '@/features/filters/defaults'
import { FiltersPanel } from '@/features/filters/filters-panel'
import { StaleFeedBanner } from '@/features/filters/stale-feed-banner'
import { useFeedUrlState } from '@/features/filters/use-feed-url-state'
import { FeedList } from '@/features/feed/feed-list'
import { PostingDetailPanel } from '@/features/feed/posting-detail-panel'
import { usePostingRoute } from '@/features/feed/routing'
import { useEscapeKey } from '@/features/feed/use-keyboard-shortcuts'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'score', label: 'Score' },
  { value: 'posted', label: 'Posted' },
  { value: 'seen', label: 'Seen' },
  { value: 'closes', label: 'Closes' },
  { value: 'company', label: 'Company' },
]

const SEARCH_DEBOUNCE_MS = 250

export function FeedScreen() {
  const { filter, sort, setFilter, setSort, resetFilters } = useFeedUrlState()
  const [searchDraft, setSearchDraft] = useState(filter.query ?? '')
  const [syncedQuery, setSyncedQuery] = useState(filter.query ?? null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const { postingId, openPosting, closePosting } = usePostingRoute()

  // The URL can change from elsewhere — a pill's ×, Reset, the Back button —
  // so the input has to fall back into line with it, not just push to it.
  // Adjusted during render rather than in an effect (React's own pattern for
  // "reset state when a prop changes"), so it never needs an extra render pass.
  if ((filter.query ?? null) !== syncedQuery) {
    setSyncedQuery(filter.query ?? null)
    setSearchDraft(filter.query ?? '')
  }

  // Débattue à 250 ms (blueprint/wp/WP11-web-filters.md §3): every keystroke
  // updates the input instantly, but the URL — and so the FTS5 request —
  // only moves once typing pauses.
  useEffect(() => {
    const trimmed = searchDraft.trim()
    if (trimmed === (filter.query ?? '')) return
    const timeout = setTimeout(() => {
      setFilter({ query: trimmed === '' ? null : trimmed })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      clearTimeout(timeout)
    }
    // Only the draft should re-arm the debounce timer; filter.query/setFilter
    // are read fresh each run without needing to restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDraft])

  useEscapeKey(() => {
    if (postingId !== null) closePosting()
  })

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <header className="flex items-center gap-4 border-b border-border px-4 py-3">
        <input
          ref={searchInputRef}
          type="search"
          placeholder="Search titles… (press / to focus)"
          aria-label="Search postings"
          value={searchDraft}
          onChange={(event) => {
            setSearchDraft(event.target.value)
          }}
          className="w-72 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-tier-possible"
        />
        <label className="ml-auto flex items-center gap-2 text-sm text-text-secondary">
          Sort
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as SortKey)
            }}
            className="rounded-md border border-border bg-surface px-2 py-1 text-text-primary"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      <StaleFeedBanner />
      <ActiveFilterPills filter={filter} onChange={setFilter} />

      <div className="flex flex-1 overflow-hidden">
        <FiltersPanel filter={filter} onChange={setFilter} onReset={resetFilters} />
        <FeedList
          filter={filter}
          sort={sort}
          searchInputRef={searchInputRef}
          isPanelOpen={postingId !== null}
          hasActiveFilters={!isDefaultFilter(filter)}
          onOpenPosting={openPosting}
        />
      </div>

      {postingId !== null && <PostingDetailPanel postingId={postingId} onClose={closePosting} />}
    </div>
  )
}
