import { describe, expect, it } from 'vitest'
import type { CompanyOut, FacetCounts, HealthSnapshot, Page, PostingDetailOut, PostingOut } from './contract'
import { POSTINGS } from './data'

describe('MSW handlers — the seven routes of blueprint/03-INTERFACES.md §3.6', () => {
  it('serves at least 2000 representative postings across GET /postings', async () => {
    expect(POSTINGS.length).toBeGreaterThanOrEqual(2000)
    const res = await fetch('/postings?limit=100')
    expect(res.status).toBe(200)
    const body = (await res.json()) as Page<PostingOut>
    expect(body.items).toHaveLength(100)
    expect(body.next_cursor).not.toBeNull()
  })

  it('paginates via an opaque cursor', async () => {
    const first = (await (await fetch('/postings?limit=50')).json()) as Page<PostingOut>
    const cursor = first.next_cursor
    expect(cursor).not.toBeNull()
    const second = (await (await fetch(`/postings?limit=50&cursor=${String(cursor)}`)).json()) as Page<PostingOut>
    const firstIds = new Set(first.items.map((i) => i.posting_id))
    expect(second.items.some((i) => firstIds.has(i.posting_id))).toBe(false)
  })

  it('includes fixtures with an absent salary, an unknown visa and an unresolved location', () => {
    expect(POSTINGS.some((p) => p.compensation.amount_min === null)).toBe(true)
    expect(POSTINGS.some((p) => p.visa_sponsorship === 'unknown')).toBe(true)
    expect(POSTINGS.some((p) => p.locations[0]?.city === null)).toBe(true)
    expect(POSTINGS.some((p) => p.locations.length > 1)).toBe(true)
    expect(POSTINGS.some((p) => p.title.length >= 80)).toBe(true)
  })

  it('GET /postings/:id returns the full detail shape', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const res = await fetch(`/postings/${target.posting_id}`)
    expect(res.status).toBe(200)
    const body = (await res.json()) as PostingDetailOut
    expect(body.posting_id).toBe(target.posting_id)
    expect(body.reasons).toBeInstanceOf(Array)
  })

  it('GET /postings/:id returns 404 for an unknown id', async () => {
    const res = await fetch('/postings/does-not-exist')
    expect(res.status).toBe(404)
  })

  it('POST /postings/:id/favorite returns 204', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const res = await fetch(`/postings/${target.posting_id}/favorite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: true }),
    })
    expect(res.status).toBe(204)
  })

  it('POST /postings/:id/hide returns 204', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const res = await fetch(`/postings/${target.posting_id}/hide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: true }),
    })
    expect(res.status).toBe(204)
  })

  it('GET /facets counts under the current filter, for the seven counted dimensions', async () => {
    const res = await fetch('/facets')
    expect(res.status).toBe(200)
    const body = (await res.json()) as FacetCounts
    expect(Object.keys(body.countries).length).toBeGreaterThan(0)
    expect(Object.keys(body.tech).length).toBeGreaterThan(0)
  })

  it('GET /facets applies invariant I6: a country filter does not zero out other countries', async () => {
    const unfiltered = (await (await fetch('/facets')).json()) as FacetCounts
    const withGbSelected = (await (await fetch('/facets?countries=GB')).json()) as FacetCounts
    const otherCountry = Object.keys(unfiltered.countries).find((c) => c !== 'GB' && unfiltered.countries[c])
    if (!otherCountry) throw new Error('fixture has no second country')
    expect(withGbSelected.countries[otherCountry]).toBe(unfiltered.countries[otherCountry])
  })

  it('GET /companies returns the registry', async () => {
    const res = await fetch('/companies')
    expect(res.status).toBe(200)
    const body = (await res.json()) as CompanyOut[]
    expect(body.length).toBeGreaterThan(0)
  })

  it('tech_all and tech_any are two distinct requests with different results', async () => {
    const all = (await (await fetch('/postings?tech_all=cpp&tech_all=python&limit=100')).json()) as Page<PostingOut>
    const any = (await (await fetch('/postings?tech_any=cpp&tech_any=python&limit=100')).json()) as Page<PostingOut>

    expect(all.items.every((item) => item.tech.includes('cpp') && item.tech.includes('python'))).toBe(true)
    expect(any.items.every((item) => item.tech.includes('cpp') || item.tech.includes('python'))).toBe(true)
    // "at least one" is never narrower than "all" over the same fixture set.
    expect(any.items.length).toBeGreaterThanOrEqual(all.items.length)
    expect(any.items.map((i) => i.posting_id)).not.toEqual(all.items.map((i) => i.posting_id))
  })

  it('GET /health returns per-source status', async () => {
    const res = await fetch('/health')
    expect(res.status).toBe(200)
    const body = (await res.json()) as HealthSnapshot
    expect(body.sources.length).toBeGreaterThan(0)
  })
})
