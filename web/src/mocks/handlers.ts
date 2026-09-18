import { HttpResponse, http } from 'msw'
import type { CompanyOut, FacetCounts, Page, PostingOut } from './contract'
import { COMPANIES_OUT, HEALTH, POSTINGS, toListItem } from './data'

// Wildcard origin: the real API has no path prefix (blueprint/03-INTERFACES.md
// §3.6), and `apiBase` in `window.__JT_CONFIG__` can point anywhere.
const API_BASE = '*'

function encodeCursor(offset: number): string {
  return btoa(String(offset))
}

function decodeCursor(cursor: string | null): number {
  if (!cursor) return 0
  const parsed = Number(atob(cursor))
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}

function scoreThenId(a: PostingOut, b: PostingOut): number {
  return b.score - a.score || a.posting_id.localeCompare(b.posting_id)
}

const SORTERS: Record<string, (a: PostingOut, b: PostingOut) => number> = {
  score: scoreThenId,
  posted: (a, b) => (b.posted_at ?? b.first_seen_at).localeCompare(a.posted_at ?? a.first_seen_at),
  seen: (a, b) => b.first_seen_at.localeCompare(a.first_seen_at),
  closes: (a, b) => {
    if (a.closes_at === null && b.closes_at === null) return 0
    if (a.closes_at === null) return 1
    if (b.closes_at === null) return -1
    return a.closes_at.localeCompare(b.closes_at)
  },
  company: (a, b) => a.company_name.localeCompare(b.company_name),
}

/**
 * The same thirteen `PostingFilter` dimensions the real `get_posting_filter`
 * dependency reads (blueprint/03-INTERFACES.md §3.5), applied to the in-memory
 * fixture set. `except` drops one dimension from the filter entirely — that's
 * how `/facets` computes each dimension's counts under every *other* filter
 * (invariant I6): a count for "country" must never be computed under the
 * country filter itself, or picking GB would zero out every other country.
 */
type ExceptDimension =
  | 'countries'
  | 'cities'
  | 'companies'
  | 'sectors'
  | 'sources'
  | 'role_families'
  | 'seniorities'
  | 'remote_modes'
  | 'tech'
  | 'visa'
  | 'tiers'
  | 'min_score'
  | 'posted_within_days'
  | 'query'
  | 'favorites_only'

function applyFilters(items: PostingOut[], params: URLSearchParams, except?: ExceptDimension): PostingOut[] {
  const set = (name: ExceptDimension, key: string) => (except === name ? new Set<string>() : new Set(params.getAll(key)))
  const countries = set('countries', 'countries')
  const cities = set('cities', 'cities')
  const companies = set('companies', 'companies')
  const sectors = set('sectors', 'sectors')
  const sources = set('sources', 'sources')
  const roleFamilies = set('role_families', 'role_families')
  const seniorities = set('seniorities', 'seniorities')
  const remoteModes = set('remote_modes', 'remote_modes')
  const visa = set('visa', 'visa')
  const tiers = set('tiers', 'tiers')
  const techAll = except === 'tech' ? [] : params.getAll('tech_all')
  const techAny = except === 'tech' ? [] : params.getAll('tech_any')
  const minScore = except === 'min_score' ? 0 : Number(params.get('min_score') ?? '0')
  const postedWithinDays = except === 'posted_within_days' ? null : params.get('posted_within_days')
  const query = except === 'query' ? null : (params.get('query')?.toLowerCase() ?? null)
  const favoritesOnly = except === 'favorites_only' ? false : params.get('favorites_only') === 'true'

  return items.filter((item) => {
    if (countries.size > 0 && !item.locations.some((l) => l.country !== null && countries.has(l.country))) {
      return false
    }
    if (cities.size > 0 && !item.locations.some((l) => l.city !== null && cities.has(l.city))) return false
    if (companies.size > 0 && !companies.has(item.company_slug)) return false
    if (sectors.size > 0 && !sectors.has(item.sector)) return false
    if (sources.size > 0 && !sources.has(item.source)) return false
    if (roleFamilies.size > 0 && !roleFamilies.has(item.role_family)) return false
    if (seniorities.size > 0 && !seniorities.has(item.seniority)) return false
    if (remoteModes.size > 0 && !item.locations.some((l) => remoteModes.has(l.remote_mode))) return false
    if (visa.size > 0 && !visa.has(item.visa_sponsorship)) return false
    if (tiers.size > 0 && !tiers.has(item.tier)) return false
    if (techAll.length > 0 && !techAll.every((t) => item.tech.includes(t))) return false
    if (techAny.length > 0 && !techAny.some((t) => item.tech.includes(t))) return false
    if (item.score < minScore) return false
    if (postedWithinDays !== null) {
      const days = Number(postedWithinDays)
      const reference = item.posted_at ?? item.first_seen_at
      const ageDays = (Date.now() - new Date(reference).getTime()) / 86_400_000
      if (ageDays > days) return false
    }
    if (favoritesOnly && !item.favorited) return false
    if (query !== null && query !== '' && !item.title.toLowerCase().includes(query)) return false
    return true
  })
}

function countBy(items: PostingOut[], pick: (item: PostingOut) => string[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const item of items) {
    for (const value of pick(item)) {
      counts[value] = (counts[value] ?? 0) + 1
    }
  }
  return counts
}

export const handlers = [
  http.get(`${API_BASE}/postings`, ({ request }) => {
    const url = new URL(request.url)
    const params = url.searchParams
    const sortKey = params.get('sort') ?? 'score'
    const limit = Math.min(Number(params.get('limit') ?? '50'), 100)
    const offset = decodeCursor(params.get('cursor'))

    const all = POSTINGS.map(toListItem)
    const filtered = applyFilters(all, params)
    const sorter = SORTERS[sortKey] ?? scoreThenId
    const sorted = [...filtered].sort(sorter)
    const page = sorted.slice(offset, offset + limit)
    const nextOffset = offset + limit
    const body: Page<PostingOut> = {
      items: page,
      next_cursor: nextOffset < sorted.length ? encodeCursor(nextOffset) : null,
    }
    return HttpResponse.json(body)
  }),

  http.get(`${API_BASE}/postings/:id`, ({ params }) => {
    const posting = POSTINGS.find((p) => p.posting_id === params.id)
    if (!posting) return new HttpResponse(null, { status: 404 })
    return HttpResponse.json(posting)
  }),

  http.post(`${API_BASE}/postings/:id/favorite`, ({ params }) => {
    const posting = POSTINGS.find((p) => p.posting_id === params.id)
    if (!posting) return new HttpResponse(null, { status: 404 })
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE}/postings/:id/hide`, ({ params }) => {
    const posting = POSTINGS.find((p) => p.posting_id === params.id)
    if (!posting) return new HttpResponse(null, { status: 404 })
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${API_BASE}/facets`, ({ request }) => {
    const params = new URL(request.url).searchParams
    const all = POSTINGS.map(toListItem)
    const notNull = <T,>(value: T | null): value is T => value !== null
    const body: FacetCounts = {
      countries: countBy(applyFilters(all, params, 'countries'), (i) =>
        i.locations.map((l) => l.country).filter(notNull),
      ),
      cities: countBy(applyFilters(all, params, 'cities'), (i) => i.locations.map((l) => l.city).filter(notNull)),
      companies: countBy(applyFilters(all, params, 'companies'), (i) => [i.company_slug]),
      sectors: countBy(applyFilters(all, params, 'sectors'), (i) => [i.sector]),
      seniorities: countBy(applyFilters(all, params, 'seniorities'), (i) => [i.seniority]),
      sources: countBy(applyFilters(all, params, 'sources'), (i) => [i.source]),
      tech: countBy(applyFilters(all, params, 'tech'), (i) => i.tech),
    }
    return HttpResponse.json(body)
  }),

  http.get(`${API_BASE}/companies`, ({ request }) => {
    const url = new URL(request.url)
    const sector = url.searchParams.get('sector')
    const country = url.searchParams.get('country')
    const body: CompanyOut[] = COMPANIES_OUT.filter(
      (c) => (!sector || c.sector === sector) && (!country || c.hq_country === country),
    )
    return HttpResponse.json(body)
  }),

  http.get(`${API_BASE}/health`, () => HttpResponse.json(HEALTH)),
]
