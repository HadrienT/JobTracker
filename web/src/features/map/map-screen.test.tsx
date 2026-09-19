import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { ToastProvider } from '@/features/favorites/toast'
import { MapScreen } from '@/features/map/map-screen'
import { POSTINGS } from '@/mocks/data'
import { server } from '@/mocks/server'
import { TooltipProvider } from '@/shared/ui/tooltip'

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <ToastProvider>
          <MapScreen />
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  window.history.pushState(null, '', '/')
})

/** The fixture pin for London, GB: several postings, so it opens a list. */
async function londonPin() {
  return await screen.findByRole('button', { name: /^London, GB — \d+ postings$/ })
}

describe('MapScreen', () => {
  it('shows one pin per city, and how many postings have no city to pin', async () => {
    renderScreen()
    await londonPin()
    expect(screen.getAllByTestId('map-pin').length).toBeGreaterThan(3)
    expect(await screen.findByRole('status')).toHaveTextContent(/on the map/)
  })

  it('opens a list of the postings behind a pin that holds several', async () => {
    const user = userEvent.setup()
    renderScreen()
    const pin = await londonPin()
    const claimed = Number(/— (\d+) postings/.exec(pin.getAttribute('aria-label') ?? '')?.[1])
    expect(claimed).toBeGreaterThan(1)

    await user.click(pin)

    const drawer = await screen.findByRole('complementary', { name: 'Postings in London, GB' })
    const list = await within(drawer).findByRole('list', { name: 'Postings' })
    await waitFor(() => {
      expect(within(list).getAllByRole('listitem').length).toBeGreaterThan(0)
    })
    // The first page holds 50 postings; a pin claiming more offers the rest behind "Load more".
    const shown = Math.min(50, claimed)
    await waitFor(() => {
      expect(within(list).getAllByRole('listitem')).toHaveLength(shown + (claimed > 50 ? 1 : 0))
    })
    if (claimed > 50) {
      expect(within(list).getByRole('button', { name: 'Load more' })).toBeInTheDocument()
    }
    expect(pin).toHaveAttribute('aria-pressed', 'true')
  })

  it('loads the next page of a long list on request', async () => {
    const user = userEvent.setup()
    renderScreen()
    await user.click(await londonPin())
    const drawer = await screen.findByRole('complementary', { name: 'Postings in London, GB' })
    const more = await within(drawer).findByRole('button', { name: 'Load more' })
    const before = within(drawer).getAllByRole('listitem').length

    await user.click(more)

    await waitFor(() => {
      expect(within(drawer).getAllByRole('listitem').length).toBeGreaterThan(before)
    })
  })

  it('opens the detail panel from the list, and closing it lands back on the list', async () => {
    const user = userEvent.setup()
    renderScreen()
    await user.click(await londonPin())
    const drawer = await screen.findByRole('complementary', { name: 'Postings in London, GB' })
    const first = (await within(drawer).findAllByRole('button', { name: /./ }))[1] // [0] is the close button
    if (!first) throw new Error('empty list')
    await user.click(first)

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(window.location.pathname).toMatch(/^\/map\/p\/.+/)

    await user.click(screen.getByTestId('posting-detail-overlay')) // the dimmed area
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/map')
    expect(screen.getByRole('complementary', { name: 'Postings in London, GB' })).toBeInTheDocument()
  })

  it('opens a single-posting pin straight into the detail panel, with no list', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    server.use(
      http.get('*/map/pins', () =>
        HttpResponse.json({
          pins: [{ city: 'Dublin', country: 'IE', lat: 53.35, lon: -6.26, count: 1, posting_id: target.posting_id }],
          total: 1,
          unplaced: 0,
        }),
      ),
    )
    const user = userEvent.setup()
    renderScreen()

    await user.click(await screen.findByRole('button', { name: 'Dublin, IE — 1 posting' }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(window.location.pathname).toBe(`/map/p/${target.posting_id}`)
    expect(screen.queryByRole('complementary', { name: /Postings in/ })).not.toBeInTheDocument()
  })

  it('closes the list with the button and with Escape', async () => {
    const user = userEvent.setup()
    renderScreen()
    await user.click(await londonPin())
    await screen.findByRole('complementary', { name: 'Postings in London, GB' })

    await user.click(screen.getByRole('button', { name: 'Close list' }))
    expect(screen.queryByRole('complementary', { name: /Postings in/ })).not.toBeInTheDocument()

    await user.click(await londonPin())
    await screen.findByRole('complementary', { name: 'Postings in London, GB' })
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('complementary', { name: /Postings in/ })).not.toBeInTheDocument()
  })

  it('applies the feed filters to the pins', async () => {
    window.history.pushState(null, '', '/map?countries=US')
    renderScreen()
    await screen.findByRole('button', { name: /^New York, US/ })
    expect(screen.queryByRole('button', { name: /^London, GB/ })).not.toBeInTheDocument()
  })

  it('says so when the pins cannot be loaded', async () => {
    server.use(http.get('*/map/pins', () => new HttpResponse(null, { status: 500 })))
    renderScreen()
    expect(await screen.findByText(/Couldn’t load the pins/)).toBeInTheDocument()
  })
})
