import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { createRef } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { FeedList } from '@/features/feed/feed-list'
import { mockViewportDimensions } from '@/features/feed/test-utils'
import { ToastProvider } from '@/features/favorites/toast'
import { server } from '@/mocks/server'
import { TooltipProvider } from '@/shared/ui/tooltip'

function renderFeed(props: Partial<React.ComponentProps<typeof FeedList>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const searchInputRef = createRef<HTMLInputElement>()
  const onOpenPosting = () => {
    /* no-op default */
  }
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <ToastProvider>
          <FeedList
            filter={{}}
            sort="score"
            searchInputRef={searchInputRef}
            isPanelOpen={false}
            hasActiveFilters={false}
            onOpenPosting={onOpenPosting}
            {...props}
          />
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...utils, searchInputRef, queryClient }
}

describe('FeedList', () => {
  let restoreViewport: () => void

  beforeEach(() => {
    restoreViewport = mockViewportDimensions(1200, 800)
  })

  afterEach(() => {
    restoreViewport()
  })

  it('keeps rendered rows under the 120-node virtualization budget with 2000 mocked postings', async () => {
    renderFeed()
    await screen.findAllByTestId('posting-row')
    const rows = screen.getAllByTestId('posting-row')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(120)
  })

  it('shows a distinct message when no postings have been collected at all', async () => {
    server.use(http.get('*/postings', () => HttpResponse.json({ items: [], next_cursor: null })))
    renderFeed()
    const empty = await screen.findByTestId('feed-empty')
    expect(empty).toHaveTextContent('No postings have been collected yet.')
  })

  it('shows a distinct message when a filter matches nothing', async () => {
    server.use(http.get('*/postings', () => HttpResponse.json({ items: [], next_cursor: null })))
    renderFeed({ filter: { query: 'no such role anywhere' }, hasActiveFilters: true })
    const empty = await screen.findByTestId('feed-empty')
    expect(empty).toHaveTextContent('No postings match this filter.')
  })

  it('moves the selection with j/k and keeps it inside the loaded rows', async () => {
    const user = userEvent.setup()
    renderFeed()
    await screen.findAllByTestId('posting-row')

    await user.keyboard('j')
    const listbox = screen.getByRole('grid', { name: 'Job postings' })
    await waitFor(() => {
      expect(listbox).toHaveAttribute('aria-activedescendant')
    })
    const firstSelected = listbox.getAttribute('aria-activedescendant')

    await user.keyboard('j')
    await waitFor(() => {
      expect(listbox.getAttribute('aria-activedescendant')).not.toBe(firstSelected)
    })
  })

  it('does not post a favorite when "f" is typed inside the search input', async () => {
    const user = userEvent.setup()
    let favoriteCalls = 0
    server.use(
      http.post('*/postings/:id/favorite', () => {
        favoriteCalls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const searchInputRef = createRef<HTMLInputElement>()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TooltipProvider>
          <ToastProvider>
            <input aria-label="search" ref={searchInputRef} />
            <FeedList
              filter={{}}
              sort="score"
              searchInputRef={searchInputRef}
              isPanelOpen={false}
              hasActiveFilters={false}
              onOpenPosting={() => undefined}
            />
          </ToastProvider>
        </TooltipProvider>
      </QueryClientProvider>,
    )
    await screen.findAllByTestId('posting-row')

    await user.keyboard('j')
    await user.click(screen.getByLabelText('search'))
    await user.keyboard('f')

    expect(favoriteCalls).toBe(0)
  })

  it('shows a toast when a favorite update fails over the network', async () => {
    const user = userEvent.setup()
    server.use(http.post('*/postings/:id/favorite', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    renderFeed()
    await screen.findAllByTestId('posting-row')

    await user.keyboard('j')
    await user.keyboard('f')

    expect(await screen.findByText('Could not update favorite — try again.')).toBeInTheDocument()
  })

  it('opens a posting on a single click, not a double click', async () => {
    const user = userEvent.setup()
    const opened: string[] = []
    renderFeed({ onOpenPosting: (id) => opened.push(id) })
    const rows = await screen.findAllByTestId('posting-row')

    const row = rows[0]
    if (!row) throw new Error('no row rendered')

    await user.click(row)

    expect(opened).toHaveLength(1)
    expect(`posting-row-${opened[0] ?? ''}`).toBe(row.id)
  })

  it('does not open a posting when its favorite star is clicked', async () => {
    const user = userEvent.setup()
    const opened: string[] = []
    renderFeed({ onOpenPosting: (id) => opened.push(id) })
    const rows = await screen.findAllByTestId('posting-row')

    const row = rows[0]
    if (!row) throw new Error('no row rendered')

    await user.click(within(row).getByRole('button', { name: /favorite/ }))

    expect(opened).toHaveLength(0)
  })

  it('hides a posting and offers an Undo that brings it back', async () => {
    const user = userEvent.setup()
    renderFeed()
    const rows = await screen.findAllByTestId('posting-row')
    const targetId = rows[0]?.id
    if (!targetId) throw new Error('no row rendered')

    await user.keyboard('j')
    await user.keyboard('h')

    await waitFor(() => {
      expect(document.getElementById(targetId)).not.toBeInTheDocument()
    })

    await user.click(await screen.findByRole('button', { name: 'Undo' }))

    await waitFor(() => {
      expect(document.getElementById(targetId)).toBeInTheDocument()
    })
  })

  it('keeps earlier pages visible and offers a retry when loading more postings fails', async () => {
    renderFeed()
    const initialRows = await screen.findAllByTestId('posting-row')
    expect(initialRows.length).toBeGreaterThan(0)

    server.use(http.get('*/postings', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    // Force the prefetch by scrolling the listbox all the way down.
    const listbox = screen.getByRole('grid', { name: 'Job postings' })
    listbox.scrollTop = 2000 * 44
    listbox.dispatchEvent(new Event('scroll', { bubbles: true }))

    const retry = await screen.findByRole('button', { name: 'Retry' })
    expect(within(listbox).getAllByTestId('posting-row').length).toBeGreaterThan(0)
    expect(retry).toBeInTheDocument()
  })
})
