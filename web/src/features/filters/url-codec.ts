import type { PostingsFilter, SortKey } from '@/api/queries'
import { DEFAULT_FILTER, DEFAULT_SORT, DEFAULT_TIERS, DEFAULT_VISA, sameStringSet } from '@/features/filters/defaults'

export interface FeedUrlState {
  filter: PostingsFilter
  sort: SortKey
}

const VALID_SENIORITIES = ['intern', 'graduate', 'junior', 'mid', 'senior', 'lead', 'unknown']
const VALID_REMOTE_MODES = ['onsite', 'hybrid', 'remote', 'unknown']
const VALID_VISA = ['sponsors', 'no', 'unknown']
const VALID_TIERS = ['strong', 'possible', 'stretch', 'rejected']
const VALID_SORT = ['score', 'posted', 'seen', 'closes', 'company']

function nonEmptyStrings(values: string[]): string[] {
  return values.filter((value) => value.trim() !== '')
}

function filterToAllowed<T extends string>(values: string[], allowed: readonly string[]): T[] {
  return values.filter((value): value is T => allowed.includes(value))
}

/** Absent param → default; every value invalid → default; at least one valid value → exactly those (a deliberate, narrower selection). */
function decodeEnumListOrDefault<T extends string>(
  params: URLSearchParams,
  key: string,
  allowed: readonly string[],
  fallback: T[],
): T[] {
  if (!params.has(key)) return fallback
  const valid = filterToAllowed<T>(params.getAll(key), allowed)
  return valid.length > 0 ? valid : fallback
}

function decodeMinScore(raw: string | null): number {
  if (raw === null) return DEFAULT_FILTER.min_score ?? 0
  const parsed = Number(raw)
  if (!Number.isFinite(parsed)) return DEFAULT_FILTER.min_score ?? 0
  return Math.min(100, Math.max(0, Math.trunc(parsed)))
}

function decodePostedWithinDays(raw: string | null): number | null {
  if (raw === null) return null
  const parsed = Number(raw)
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : null
}

/**
 * Tolerant by design (blueprint/wp/WP11-web-filters.md §2): an unknown param is
 * simply never read here, and an invalid value for a known param falls back to
 * its default instead of throwing — an old, bookmarked, or hand-edited URL
 * always renders *something* sensible.
 */
export function decodeFeedState(params: URLSearchParams): FeedUrlState {
  const sortRaw = params.get('sort')
  const sort = (sortRaw !== null && VALID_SORT.includes(sortRaw) ? sortRaw : DEFAULT_SORT) as SortKey

  const queryRaw = params.get('query')
  const query = queryRaw !== null && queryRaw.trim() !== '' ? queryRaw : null

  const filter: PostingsFilter = {
    countries: nonEmptyStrings(params.getAll('countries')),
    cities: nonEmptyStrings(params.getAll('cities')),
    companies: nonEmptyStrings(params.getAll('companies')),
    sectors: nonEmptyStrings(params.getAll('sectors')),
    seniorities: filterToAllowed(params.getAll('seniorities'), VALID_SENIORITIES),
    remote_modes: filterToAllowed(params.getAll('remote_modes'), VALID_REMOTE_MODES),
    tech_all: nonEmptyStrings(params.getAll('tech_all')),
    tech_any: nonEmptyStrings(params.getAll('tech_any')),
    visa: decodeEnumListOrDefault(params, 'visa', VALID_VISA, DEFAULT_VISA),
    tiers: decodeEnumListOrDefault(params, 'tiers', VALID_TIERS, DEFAULT_TIERS),
    min_score: decodeMinScore(params.get('min_score')),
    posted_within_days: decodePostedWithinDays(params.get('posted_within_days')),
    query,
    favorites_only: params.get('favorites_only') === 'true',
  }

  return { filter, sort }
}

function appendListUnlessDefault(
  params: URLSearchParams,
  key: string,
  values: readonly string[] | undefined,
  defaults: readonly string[],
) {
  const list = values ?? []
  if (sameStringSet(list, defaults)) return
  for (const value of list) params.append(key, value)
}

/**
 * The inverse of `decodeFeedState`. A field equal to its own default is
 * omitted — `decodeFeedState` reconstructs it from the same default, so the
 * round trip holds and shared URLs stay short instead of spelling out all
 * thirteen dimensions on every load.
 */
export function encodeFeedState(state: FeedUrlState): URLSearchParams {
  const params = new URLSearchParams()
  const { filter, sort } = state

  appendListUnlessDefault(params, 'countries', filter.countries, DEFAULT_FILTER.countries ?? [])
  appendListUnlessDefault(params, 'cities', filter.cities, DEFAULT_FILTER.cities ?? [])
  appendListUnlessDefault(params, 'companies', filter.companies, DEFAULT_FILTER.companies ?? [])
  appendListUnlessDefault(params, 'sectors', filter.sectors, DEFAULT_FILTER.sectors ?? [])
  appendListUnlessDefault(params, 'seniorities', filter.seniorities, DEFAULT_FILTER.seniorities ?? [])
  appendListUnlessDefault(params, 'remote_modes', filter.remote_modes, DEFAULT_FILTER.remote_modes ?? [])
  appendListUnlessDefault(params, 'tech_all', filter.tech_all, DEFAULT_FILTER.tech_all ?? [])
  appendListUnlessDefault(params, 'tech_any', filter.tech_any, DEFAULT_FILTER.tech_any ?? [])
  appendListUnlessDefault(params, 'visa', filter.visa, DEFAULT_VISA)
  appendListUnlessDefault(params, 'tiers', filter.tiers, DEFAULT_TIERS)

  if ((filter.min_score ?? 0) !== 0) params.set('min_score', String(filter.min_score))
  if (filter.posted_within_days !== null && filter.posted_within_days !== undefined) {
    params.set('posted_within_days', String(filter.posted_within_days))
  }
  if (filter.query) params.set('query', filter.query)
  if (filter.favorites_only) params.set('favorites_only', 'true')
  if (sort !== DEFAULT_SORT) params.set('sort', sort)

  return params
}
