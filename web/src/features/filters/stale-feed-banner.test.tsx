import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { StaleFeedBanner } from '@/features/filters/stale-feed-banner'
import { HEALTH } from '@/mocks/data'
import { server } from '@/mocks/server'

function renderBanner() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <StaleFeedBanner />
    </QueryClientProvider>,
  )
}

describe('StaleFeedBanner', () => {
  it('renders nothing while the feed is fresh', () => {
    const { container } = renderBanner()
    expect(container).toBeEmptyDOMElement()
  })

  it('shows a warning banner when the feed is stale — P3 on the feed, not a separate status page', async () => {
    server.use(http.get('*/health', () => HttpResponse.json({ ...HEALTH, feed: { ...HEALTH.feed, stale: true } })))
    renderBanner()
    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent(/hasn't refreshed recently/)
  })
})
