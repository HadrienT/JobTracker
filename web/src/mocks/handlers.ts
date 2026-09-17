import { HttpResponse, http } from 'msw'
import type {
  CompanyOut,
  FacetBucket,
  FacetCounts,
  Page,
  PostingOut,
  Seniority,
  Tier,
  VisaStatus,
} from './contract'
import { COMPANIES_OUT, HEALTH, POSTINGS, toListItem } from './data'

const API_BASE = '*/api'

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

function applyFilters(items: PostingOut[], params: URLSearchParams): PostingOut[] {
  const countries = new Set(params.getAll('countries'))
  const companies = new Set(params.getAll('companies'))
  const sectors = new Set(params.getAll('sectors'))
  const seniorities = new Set(params.getAll('seniorities') as Seniority[])
  const remoteModes = new Set(params.getAll('remote_modes'))
  const visa = new Set(params.getAll('visa') as VisaStatus[])
  const tiers = new Set(params.getAll('tiers') as Tier[])
  const minScore = Number(params.get('min_score') ?? '0')
  const query = params.get('query')?.toLowerCase() ?? null
  const favoritesOnly = params.get('favorites_only') === 'true'

  return items.filter((item) => {
    if (countries.size > 0 && !item.locations.some((l) => l.country !== null && countries.has(l.country))) {
      return false
    }
    if (companies.size > 0 && !companies.has(item.company_slug)) return false
    if (sectors.size > 0 && !sectors.has(item.sector)) return false
    if (seniorities.size > 0 && !seniorities.has(item.seniority)) return false
    if (
      remoteModes.size > 0 &&
      !item.locations.some((l) => remoteModes.has(l.remote_mode))
    ) {
      return false
    }
    if (visa.size > 0 && !visa.has(item.visa_sponsorship)) return false
    if (tiers.size > 0 && !tiers.has(item.tier)) return false
    if (item.score < minScore) return false
    if (favoritesOnly && !item.favorited) return false
    if (query && !item.title.toLowerCase().includes(query)) return false
    return true
  })
}

function bucketize(items: PostingOut[], pick: (item: PostingOut) => string[]): FacetBucket[] {
  const counts = new Map<string, number>()
  for (const item of items) {
    for (const value of pick(item)) {
      counts.set(value, (counts.get(value) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, label: value, count }))
    .sort((a, b) => b.count - a.count)
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
    const url = new URL(request.url)
    const all = POSTINGS.map(toListItem)
    const filtered = applyFilters(all, url.searchParams)
    const body: FacetCounts = {
      countries: bucketize(filtered, (i) => i.locations.map((l) => l.country).filter((c) => c !== null)),
      cities: bucketize(filtered, (i) => i.locations.map((l) => l.city).filter((c) => c !== null)),
      companies: bucketize(filtered, (i) => [i.company_slug]),
      sectors: bucketize(filtered, (i) => [i.sector]),
      role_families: bucketize(filtered, (i) => [i.role_family]),
      seniorities: bucketize(filtered, (i) => [i.seniority]),
      remote_modes: bucketize(filtered, (i) => i.locations.map((l) => l.remote_mode)),
      tech: bucketize(filtered, (i) => i.tech),
      visa: bucketize(filtered, (i) => [i.visa_sponsorship]),
      tiers: bucketize(filtered, (i) => [i.tier]),
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
