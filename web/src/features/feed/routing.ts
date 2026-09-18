import { useCallback, useEffect, useState } from 'react'

const DETAIL_PATH_PREFIX = '/p/'

function readPostingId(pathname: string): string | null {
  if (!pathname.startsWith(DETAIL_PATH_PREFIX)) return null
  const id = pathname.slice(DETAIL_PATH_PREFIX.length)
  return id === '' ? null : decodeURIComponent(id)
}

/**
 * `/p/{id}` is a real, shareable, reloadable URL, but it never navigates away —
 * it's rendered as an overlay on top of the feed, which stays mounted underneath
 * and keeps its scroll position (blueprint/wp/WP10-web-feed.md §5).
 */
export function usePostingRoute(): {
  postingId: string | null
  openPosting: (id: string) => void
  closePosting: () => void
} {
  const [postingId, setPostingId] = useState<string | null>(() => readPostingId(window.location.pathname))

  useEffect(() => {
    function onPopState() {
      setPostingId(readPostingId(window.location.pathname))
    }
    window.addEventListener('popstate', onPopState)
    return () => {
      window.removeEventListener('popstate', onPopState)
    }
  }, [])

  const openPosting = useCallback((id: string) => {
    window.history.pushState(null, '', `${DETAIL_PATH_PREFIX}${encodeURIComponent(id)}`)
    setPostingId(id)
  }, [])

  const closePosting = useCallback(() => {
    window.history.pushState(null, '', '/')
    setPostingId(null)
  }, [])

  return { postingId, openPosting, closePosting }
}
