/**
 * The single request builder for the whole front (blueprint/wp/WP10-web-feed.md
 * §2): headers, base URL and error normalization live here once, and every hook
 * in `queries.ts` goes through it instead of calling `fetch` directly.
 *
 * The base URL comes from `window.__JT_CONFIG__`, injected by nginx at container
 * start — never from `import.meta.env`, which would bake the URL into the build
 * (blueprint/12-WEB-UI.md §9).
 */
import type { components, operations } from '@/api/schema.gen'

declare global {
  interface Window {
    __JT_CONFIG__?: { apiBase: string }
  }
}

type Schemas = components['schemas']
type PostingsQuery = NonNullable<operations['get_postings_postings_get']['parameters']['query']>
type FacetsQuery = NonNullable<operations['get_facets_facets_get']['parameters']['query']>
type MapPinsQuery = NonNullable<operations['get_map_pins_map_pins_get']['parameters']['query']>
type CompaniesQuery = NonNullable<operations['get_companies_companies_get']['parameters']['query']>

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function apiBase(): string {
  return window.__JT_CONFIG__?.apiBase ?? ''
}

/** Repeated-param form (`?countries=GB&countries=US`) — what FastAPI expects, not CSV. */
function buildSearch(query: object): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined) continue
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) search.append(key, String(item))
    } else {
      search.append(key, String(value))
    }
  }
  const qs = search.toString()
  return qs === '' ? '' : `?${qs}`
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const { detail } = body
      return typeof detail === 'string' ? detail : JSON.stringify(detail)
    }
  } catch {
    // response body wasn't JSON — fall through to statusText below
  }
  return response.statusText || `request failed with status ${String(response.status)}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has('content-type')) headers.set('content-type', 'application/json')
  const response = await fetch(`${apiBase()}${path}`, { ...init, headers })
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  listPostings(query: PostingsQuery): Promise<Schemas['PostingsPage']> {
    return request(`/postings${buildSearch(query)}`)
  },
  getMapPins(query: MapPinsQuery): Promise<Schemas['MapPins']> {
    return request(`/map/pins${buildSearch(query)}`)
  },
  getPostingDetail(postingId: string): Promise<Schemas['PostingDetailOut']> {
    return request(`/postings/${encodeURIComponent(postingId)}`)
  },
  setFavorite(postingId: string, value: boolean): Promise<void> {
    return request(`/postings/${encodeURIComponent(postingId)}/favorite`, {
      method: 'POST',
      body: JSON.stringify({ value } satisfies Schemas['FlagRequest']),
    })
  },
  setHidden(postingId: string, value: boolean): Promise<void> {
    return request(`/postings/${encodeURIComponent(postingId)}/hide`, {
      method: 'POST',
      body: JSON.stringify({ value } satisfies Schemas['FlagRequest']),
    })
  },
  getFacets(query: FacetsQuery): Promise<Schemas['FacetCounts']> {
    return request(`/facets${buildSearch(query)}`)
  },
  getCompanies(query: CompaniesQuery): Promise<Schemas['CompanyOut'][]> {
    return request(`/companies${buildSearch(query)}`)
  },
  getHealth(): Promise<Schemas['HealthSnapshot']> {
    return request('/health')
  },
}

export type { PostingsQuery, FacetsQuery, CompaniesQuery, MapPinsQuery }
