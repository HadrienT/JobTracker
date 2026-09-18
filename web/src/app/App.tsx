import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { useAppRoute } from '@/app/routes'
import { ThemeProvider } from '@/app/theme-provider'
import { TopNav } from '@/app/top-nav'
import { CompaniesScreen } from '@/features/filters/companies-screen'
import { HealthScreen } from '@/features/filters/health-screen'
import { ToastProvider } from '@/features/favorites/toast'
import { FeedScreen } from '@/features/feed/feed-screen'
import { TooltipProvider } from '@/shared/ui/tooltip'

export function App() {
  // Created per mount, not at module scope: each test render (and each future
  // Storybook story) gets its own cache instead of leaking state across them.
  const [queryClient] = useState(() => new QueryClient())
  const { route, navigate } = useAppRoute()

  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={150}>
          <ToastProvider>
            <div className="flex h-dvh flex-col bg-background text-text-primary">
              <TopNav route={route} navigate={navigate} />
              <div className="flex flex-1 overflow-hidden">
                {route === 'feed' && <FeedScreen />}
                {route === 'companies' && <CompaniesScreen />}
                {route === 'health' && <HealthScreen />}
              </div>
            </div>
          </ToastProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
