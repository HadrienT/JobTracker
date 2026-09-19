import { useCallback, useEffect, useState } from 'react'

function readPostingId(pathname: string, detailPrefix: string): string | null {
  if (!pathname.startsWith(detailPrefix)) return null
  const id = pathname.slice(detailPrefix.length)
  return id === '' ? null : decodeURIComponent(id)
}

/**
 * `/p/{id}` is a real, shareable, reloadable URL, but it never navigates away —
 * it's rendered as an overlay on top of the feed, which stays mounted underneath
 * and keeps its scroll position (blueprint/wp/WP10-web-feed.md §5). The query string
 * — the filters and the sort, the only source of truth for the feed (ADR-008) — rides
 * along both ways: dropping it would silently reset the feed the moment a detail is
 * closed, and a reload of `/p/{id}` would come back unfiltered.
 *
 * `basePath` is the screen the overlay sits on: '' for the feed (`/p/{id}`), '/map' for the
 * map (`/map/p/{id}`) — closing returns to that screen, not to the feed.
 */
export function usePostingRoute(basePath = ''): {
  postingId: string | null
  openPosting: (id: string) => void
  closePosting: () => void
} {
  const detailPrefix = `${basePath}/p/`
  const [postingId, setPostingId] = useState<string | null>(() =>
    readPostingId(window.location.pathname, detailPrefix),
  )

  useEffect(() => {
    function onPopState() {
      setPostingId(readPostingId(window.location.pathname, detailPrefix))
    }
    window.addEventListener('popstate', onPopState)
    return () => {
      window.removeEventListener('popstate', onPopState)
    }
  }, [detailPrefix])

  const openPosting = useCallback((id: string) => {
    window.history.pushState(null, '', `${detailPrefix}${encodeURIComponent(id)}${window.location.search}`)
    setPostingId(id)
  }, [detailPrefix])

  const closePosting = useCallback(() => {
    window.history.pushState(null, '', `${basePath === '' ? '/' : basePath}${window.location.search}`)
    setPostingId(null)
  }, [basePath])

  return { postingId, openPosting, closePosting }
}
