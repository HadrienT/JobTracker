import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { api } from '@/api/client'
import { server } from '@/mocks/server'

afterEach(() => {
  delete window.__JT_CONFIG__
})

describe('api client', () => {
  it('reads the base URL from window.__JT_CONFIG__, never import.meta.env', async () => {
    window.__JT_CONFIG__ = { apiBase: 'http://example.test' }
    let capturedUrl = ''
    server.use(
      http.get('http://example.test/postings', ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )
    await api.listPostings({})
    expect(capturedUrl.startsWith('http://example.test/postings')).toBe(true)
  })

  it('sends array filters in repeated-param form, not CSV', async () => {
    let capturedUrl = ''
    server.use(
      http.get('*/postings', ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )
    await api.listPostings({ countries: ['GB', 'US'], min_score: 40 })
    const url = new URL(capturedUrl)
    expect(url.searchParams.getAll('countries')).toEqual(['GB', 'US'])
    expect(url.searchParams.get('min_score')).toBe('40')
  })

  it('omits null and undefined query values entirely', async () => {
    let capturedUrl = ''
    server.use(
      http.get('*/postings', ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )
    await api.listPostings({ cursor: null, posted_within_days: undefined })
    const url = new URL(capturedUrl)
    expect(url.searchParams.has('cursor')).toBe(false)
    expect(url.searchParams.has('posted_within_days')).toBe(false)
  })

  it('normalizes a non-2xx JSON body into a single ApiError shape', async () => {
    server.use(http.get('*/postings', () => HttpResponse.json({ detail: 'bad filter' }, { status: 400 })))
    await expect(api.listPostings({})).rejects.toMatchObject({ status: 400, message: 'bad filter' })
  })

  it('resolves a 204 response to undefined', async () => {
    server.use(http.post('*/postings/:id/favorite', () => new HttpResponse(null, { status: 204 })))
    await expect(api.setFavorite('abc', true)).resolves.toBeUndefined()
  })
})
