import { useEffect, useState } from 'react'

export type RouteName = 'feed' | 'map' | 'companies' | 'health'

function routeFor(pathname: string): RouteName {
  if (pathname.startsWith('/map')) return 'map'
  if (pathname.startsWith('/companies')) return 'companies'
  if (pathname.startsWith('/health')) return 'health'
  return 'feed'
}

/**
 * Top-level screen routing (`/`, `/map`, `/companies`, `/health`). `/p/{id}` and
 * `/map/p/{id}` are not screens — they are the detail overlay the feed / the map manage
 * themselves on top of their own screen (see `features/feed/routing.ts`).
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
