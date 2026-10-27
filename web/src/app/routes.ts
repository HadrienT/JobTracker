import { useEffect, useState } from 'react'

export type RouteName = 'feed' | 'swiss' | 'tech' | 'applications' | 'map' | 'companies' | 'health'

function routeFor(pathname: string): RouteName {
  if (pathname === '/ch' || pathname.startsWith('/ch/')) return 'swiss'
  if (pathname === '/tech' || pathname.startsWith('/tech/')) return 'tech'
  if (pathname.startsWith('/applications')) return 'applications'
  if (pathname.startsWith('/map')) return 'map'
  if (pathname.startsWith('/companies')) return 'companies'
  if (pathname.startsWith('/health')) return 'health'
  return 'feed'
}

/**
 * Top-level screen routing (`/`, `/ch`, `/tech`, `/applications`, `/map`, `/companies`, `/health`).
 * `/p/{id}`, `/ch/p/{id}`, `/tech/p/{id}`, `/map/p/{id}` and `/applications/p/{id}` are not screens — they are
 * the detail overlay each screen manages itself on top of its own list (see
 * `features/feed/routing.ts`). `/ch` is the `ch_tech` track and `/tech` the `tech` one
 * (blueprint/wp/WP20-tracks.md): the same feed, scored against its own profile.
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
