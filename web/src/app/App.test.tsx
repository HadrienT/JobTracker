import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '@/app/App'
import { server } from '@/mocks/server'

function navButton(name: string): HTMLElement {
  return within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name })
}

/** Every API request the page makes, as URLs — what reached the server, not what was meant to. */
function recordRequests(): URL[] {
  const seen: URL[] = []
  server.use(
    // Returning nothing falls through to the regular mock handlers.
    http.get('*', ({ request }) => {
      seen.push(new URL(request.url))
    }),
  )
  return seen
}

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('App', () => {
  it('offers the current feed as a CSV, under the same filters and sort', async () => {
    window.history.pushState(null, '', '/?countries=GB&sort=seen')
    render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })

    const link = screen.getByRole('link', { name: 'Export CSV' })
    const url = new URL(link.getAttribute('href') ?? '', 'http://x')

    expect(url.pathname).toBe('/export/postings.csv')
    expect(url.searchParams.getAll('countries')).toEqual(['GB'])
    expect(url.searchParams.get('sort')).toBe('seen')
  })

  it('renders the feed screen with no serious axe violations', async () => {
    const { container } = render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('the Swiss tech tab is the same feed, asking for the ch_tech track', async () => {
    const seen = recordRequests()
    window.history.pushState(null, '', '/ch?seniorities=junior')
    render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })

    expect(navButton('Swiss tech')).toHaveAttribute('aria-current', 'page')
    await waitFor(() => {
      expect(seen.some((url) => url.pathname.endsWith('/facets'))).toBe(true)
    })
    for (const url of seen.filter((u) => /\/(postings|facets)$/.test(u.pathname))) {
      expect(url.searchParams.get('track')).toBe('ch_tech')
      expect(url.searchParams.getAll('seniorities')).toEqual(['junior'])
    }
    // the track belongs to the screen, not to the address bar
    expect(new URLSearchParams(window.location.search).get('track')).toBeNull()
    const csv = new URL(screen.getByRole('link', { name: 'Export CSV' }).getAttribute('href') ?? '', 'http://x')
    expect(csv.searchParams.get('track')).toBe('ch_tech')
  })

  it('the Tech tab asks for the tech track', async () => {
    const seen = recordRequests()
    window.history.pushState(null, '', '/tech')
    render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })

    expect(navButton('Tech')).toHaveAttribute('aria-current', 'page')
    await waitFor(() => {
      expect(seen.some((url) => url.pathname.endsWith('/postings'))).toBe(true)
    })
    for (const url of seen.filter((u) => /\/(postings|facets)$/.test(u.pathname))) {
      expect(url.searchParams.get('track')).toBe('tech')
    }
  })

  it('the quant feed never sends a track', async () => {
    const seen = recordRequests()
    render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })
    await waitFor(() => {
      expect(seen.some((url) => url.pathname.endsWith('/postings'))).toBe(true)
    })
    expect(seen.every((url) => !url.searchParams.has('track'))).toBe(true)
  })

  it('switching tabs moves between the feeds', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })

    await user.click(navButton('Swiss tech'))
    expect(window.location.pathname).toBe('/ch')
    await screen.findByRole('grid', { name: 'Job postings' })

    await user.click(navButton('Feed'))
    expect(window.location.pathname).toBe('/')
  })
})
