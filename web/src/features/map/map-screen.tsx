import { useState } from 'react'
import { useMapPins } from '@/api/queries'
import { ActiveFilterPills } from '@/features/filters/active-filter-pills'
import { FiltersPanel } from '@/features/filters/filters-panel'
import { StaleFeedBanner } from '@/features/filters/stale-feed-banner'
import { useFeedUrlState } from '@/features/filters/use-feed-url-state'
import { PostingDetailPanel } from '@/features/feed/posting-detail-panel'
import { usePostingRoute } from '@/features/feed/routing'
import { useEscapeKey } from '@/features/feed/use-keyboard-shortcuts'
import { PinListPanel, type Place } from '@/features/map/pin-list-panel'
import { pinKey, type MapPin } from '@/features/map/pin-utils'
import { WorldMap } from '@/features/map/world-map'
import { isDefaultFilter } from '@/features/filters/defaults'

/**
 * The feed, on a map: same filters (and the same URL state), one pin per city. A pin that holds
 * a single posting opens it straight away; a pin that holds several opens the list of them in a
 * drawer, and choosing one opens the detail panel — `/map/p/{id}`, so the URL is shareable and
 * closing the panel comes back to the map, not to the feed.
 */
export function MapScreen() {
  const { filter, setFilter, resetFilters } = useFeedUrlState()
  const { postingId, openPosting, closePosting } = usePostingRoute('/map')
  const [place, setPlace] = useState<Place | null>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const pinsQuery = useMapPins(filter)
  const pins = pinsQuery.data?.pins ?? []

  useEscapeKey(() => {
    if (postingId !== null) closePosting()
    else if (filtersOpen) setFiltersOpen(false)
    else setPlace(null)
  })

  // A pin the new filter no longer produces has nothing left to list: drop the drawer with it.
  const selectedPin = place ? pins.find((pin) => pinKey(pin) === pinKey(place)) : undefined
  if (place !== null && pinsQuery.isSuccess && !pinsQuery.isPlaceholderData && !selectedPin) {
    setPlace(null)
  }

  function onSelectPin(pin: MapPin) {
    if (pin.count === 1 && pin.posting_id !== null) {
      openPosting(pin.posting_id)
      return
    }
    setPlace({ country: pin.country, city: pin.city })
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <StaleFeedBanner />
      <ActiveFilterPills filter={filter} onChange={setFilter} />

      <div className="relative flex flex-1 overflow-hidden">
        <FiltersPanel
          filter={filter}
          onChange={setFilter}
          onReset={resetFilters}
          open={filtersOpen}
          onClose={() => {
            setFiltersOpen(false)
          }}
        />

        <div className="relative flex-1 overflow-hidden">
          <WorldMap pins={pins} selectedKey={place ? pinKey(place) : null} onSelectPin={onSelectPin} />

          <button
            type="button"
            onClick={() => {
              setFiltersOpen(true)
            }}
            className="absolute left-3 top-3 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text-secondary hover:text-text-primary md:hidden"
          >
            Filters
            {!isDefaultFilter(filter) && (
              <span aria-label="(active)" className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-tier-possible" />
            )}
          </button>

          <p
            role="status"
            className="pointer-events-none absolute bottom-3 left-3 right-3 rounded-md md:right-auto border border-border bg-surface/90 px-3 py-1.5 text-xs text-text-secondary"
          >
            {pinsQuery.isError && 'Couldn’t load the pins.'}
            {pinsQuery.data &&
              `${String(pinsQuery.data.total)} postings · ${String(pinsQuery.data.total - pinsQuery.data.unplaced)} on the map${
                pinsQuery.data.unplaced > 0
                  ? ` · ${String(pinsQuery.data.unplaced)} without a city (remote or country only)`
                  : ''
              }`}
            {pinsQuery.isPending && 'Loading postings…'}
          </p>
        </div>

        {place && selectedPin && (
          <PinListPanel
            filter={filter}
            place={place}
            count={selectedPin.count}
            onOpenPosting={openPosting}
            onClose={() => {
              setPlace(null)
            }}
          />
        )}
      </div>

      {postingId !== null && <PostingDetailPanel postingId={postingId} onClose={closePosting} />}
    </div>
  )
}
