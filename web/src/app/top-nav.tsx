import type { RouteName } from '@/app/routes'
import { cn } from '@/shared/lib/cn'

const LINKS: { route: RouteName; path: string; label: string }[] = [
  { route: 'feed', path: '/', label: 'Feed' },
  { route: 'swiss', path: '/ch', label: 'Swiss tech' },
  { route: 'tech', path: '/tech', label: 'Tech' },
  { route: 'applications', path: '/applications', label: 'Applications' },
  { route: 'map', path: '/map', label: 'Map' },
  { route: 'companies', path: '/companies', label: 'Companies' },
  { route: 'health', path: '/health', label: 'Health' },
]

interface TopNavProps {
  route: RouteName
  navigate: (path: string) => void
}

export function TopNav({ route, navigate }: TopNavProps) {
  return (
    // On a phone the seven tabs don't fit: the row scrolls sideways rather than wrapping.
    <nav aria-label="Main" className="flex items-center gap-4 border-b border-border px-4 py-2">
      {/* A full reload, not a refetch: the one way to pick up a freshly deployed front on a phone. */}
      <button
        type="button"
        title="Reload this page"
        onClick={() => {
          window.location.reload()
        }}
        className="shrink-0 text-sm font-semibold text-text-primary hover:text-tier-possible"
      >
        JobTracker
      </button>
      <ul className="no-scrollbar -mx-2 flex min-w-0 gap-1 overflow-x-auto px-2 md:mx-0 md:px-0">
        {LINKS.map((link) => (
          <li key={link.route}>
            <a
              href={link.path}
              aria-current={route === link.route ? 'page' : undefined}
              onClick={(event) => {
                // Middle-click, ctrl/cmd/shift-click: let the browser open a new tab or window.
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                event.preventDefault()
                navigate(link.path)
              }}
              className={cn(
                'block whitespace-nowrap rounded-md px-2 py-1.5 text-sm md:py-1',
                route === link.route ? 'bg-surface-elevated text-text-primary' : 'text-text-secondary hover:text-text-primary',
              )}
            >
              {link.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
