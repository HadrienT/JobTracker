import { useEffect, useState } from 'react'

export type RouteName = 'feed' | 'companies' | 'health'

function routeFor(pathname: string): RouteName {
  if (pathname.startsWith('/companies')) return 'companies'
  if (pathname.startsWith('/health')) return 'health'
  return 'feed'
}

/**
 * Top-level screen routing (`/`, `/companies`, `/health`). `/p/{id}` is not a
 * screen here — it's an overlay `FeedScreen` manages itself on top of the feed
 * (see `features/feed/routing.ts`), so it isn't one of the three route names.
 */
export function useAppRoute(): { route: RouteName; navigate: (path: string) => void } {
  const [pathname, setPathname] = useState(() => window.location.pathname)

  useEffect(() => {
    function onPopState() {
      setPathname(window.location.pathname)
    }
    window.addEventListener('popstate', onPopState)
    return () => {
      window.removeEventListener('popstate', onPopState)
    }
  }, [])

  return {
    route: routeFor(pathname),
    navigate: (path: string) => {
      window.history.pushState(null, '', path)
      setPathname(path)
    },
  }
}
