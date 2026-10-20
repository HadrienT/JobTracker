import { useEffect, useState } from 'react'

export type RouteName = 'feed' | 'swiss' | 'map' | 'companies' | 'health'

function routeFor(pathname: string): RouteName {
  if (pathname === '/ch' || pathname.startsWith('/ch/')) return 'swiss'
  if (pathname.startsWith('/map')) return 'map'
  if (pathname.startsWith('/companies')) return 'companies'
  if (pathname.startsWith('/health')) return 'health'
  return 'feed'
}

/**
 * Top-level screen routing (`/`, `/ch`, `/map`, `/companies`, `/health`). `/p/{id}`,
 * `/ch/p/{id}` and `/map/p/{id}` are not screens — they are the detail overlay the feed / the
 * Swiss tech feed / the map manage themselves on top of their own screen (see
 * `features/feed/routing.ts`). `/ch` is the `ch_tech` track (blueprint/wp/WP20-tracks.md): the
 * same feed, scored against its own profile.
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
