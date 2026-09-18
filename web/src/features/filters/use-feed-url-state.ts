import { useEffect, useState } from 'react'
import type { PostingsFilter, SortKey } from '@/api/queries'
import { DEFAULT_FILTER } from '@/features/filters/defaults'
import { decodeFeedState, encodeFeedState, type FeedUrlState } from '@/features/filters/url-codec'

/**
 * `URLSearchParams` is the only source of truth for filter/sort state
 * (ADR-008) — there is deliberately no store here to keep in sync. Every
 * change is a `pushState`, so the browser Back button walks through the
 * filter history one step at a time.
 */
export function useFeedUrlState(): {
  filter: PostingsFilter
  sort: SortKey
  setFilter: (patch: Partial<PostingsFilter>) => void
  setSort: (sort: SortKey) => void
  resetFilters: () => void
} {
  const [state, setState] = useState<FeedUrlState>(() => decodeFeedState(new URLSearchParams(window.location.search)))

  useEffect(() => {
    function onPopState() {
      setState(decodeFeedState(new URLSearchParams(window.location.search)))
    }
    window.addEventListener('popstate', onPopState)
    return () => {
      window.removeEventListener('popstate', onPopState)
    }
  }, [])

  function pushState(next: FeedUrlState) {
    const qs = encodeFeedState(next).toString()
    const url = qs === '' ? window.location.pathname : `${window.location.pathname}?${qs}`
    window.history.pushState(null, '', url)
    setState(next)
  }

  return {
    filter: state.filter,
    sort: state.sort,
    setFilter: (patch) => {
      pushState({ filter: { ...state.filter, ...patch }, sort: state.sort })
    },
    setSort: (sort) => {
      pushState({ filter: state.filter, sort })
    },
    resetFilters: () => {
      pushState({ filter: DEFAULT_FILTER, sort: state.sort })
    },
  }
}
