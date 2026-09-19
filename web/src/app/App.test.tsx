import { render, screen } from '@testing-library/react'
import { axe } from 'jest-axe'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '@/app/App'

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
})
