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
    <nav aria-label="Main" className="flex items-center gap-4 border-b border-border px-4 py-2">
      <span className="text-sm font-semibold text-text-primary">JobTracker</span>
      <ul className="flex gap-1">
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
                'block rounded-md px-2 py-1 text-sm',
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
