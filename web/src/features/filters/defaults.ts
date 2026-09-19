import type { PostingsFilter, SortKey } from '@/api/queries'
import type { ApplicationStatus } from '@/api/queries'
import type { RemoteMode, Seniority, Tier, VisaStatus } from '@/mocks/contract'

/**
 * Mirrors `get_posting_filter` (`src/jobtracker/api/deps.py`): the server applies
 * these same defaults when a param is entirely absent from the query string.
 * The front encodes them explicitly once decoded (blueprint/wp/WP11-web-filters.md
 * §2) so a shared URL always shows the full, self-describing filter state.
 */
export const DEFAULT_SORT: SortKey = 'score'
export const DEFAULT_VISA: VisaStatus[] = ['sponsors', 'unknown']
export const DEFAULT_TIERS: Tier[] = ['strong', 'possible', 'stretch']

export const DEFAULT_FILTER: PostingsFilter = {
  countries: [],
  cities: [],
  companies: [],
  sectors: [],
  seniorities: [],
  remote_modes: [],
  tech_all: [],
  tech_any: [],
  visa: DEFAULT_VISA,
  tiers: DEFAULT_TIERS,
  min_score: 0,
  posted_within_days: null,
  query: null,
  favorites_only: false,
  statuses: [],
}

export function sameStringSet(a: readonly string[] = [], b: readonly string[] = []): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every((value) => set.has(value))
}

/** Used to tell "no results under this filter" from "the feed itself is empty", and to enable/disable Reset. */
export function isDefaultFilter(filter: PostingsFilter): boolean {
  return (
    sameStringSet(filter.countries, DEFAULT_FILTER.countries) &&
    sameStringSet(filter.cities, DEFAULT_FILTER.cities) &&
    sameStringSet(filter.companies, DEFAULT_FILTER.companies) &&
    sameStringSet(filter.sectors, DEFAULT_FILTER.sectors) &&
    sameStringSet(filter.seniorities, DEFAULT_FILTER.seniorities) &&
    sameStringSet(filter.remote_modes, DEFAULT_FILTER.remote_modes) &&
    sameStringSet(filter.tech_all, DEFAULT_FILTER.tech_all) &&
    sameStringSet(filter.tech_any, DEFAULT_FILTER.tech_any) &&
    sameStringSet(filter.visa, DEFAULT_FILTER.visa) &&
    sameStringSet(filter.tiers, DEFAULT_FILTER.tiers) &&
    (filter.min_score ?? 0) === DEFAULT_FILTER.min_score &&
    (filter.posted_within_days ?? null) === DEFAULT_FILTER.posted_within_days &&
    (filter.query ?? null) === DEFAULT_FILTER.query &&
    (filter.favorites_only ?? false) === DEFAULT_FILTER.favorites_only &&
    sameStringSet(filter.statuses, DEFAULT_FILTER.statuses)
  )
}

export const SENIORITY_OPTIONS: { value: Seniority; label: string }[] = [
  { value: 'intern', label: 'Intern' },
  { value: 'graduate', label: 'Graduate' },
  { value: 'junior', label: 'Junior' },
  { value: 'mid', label: 'Mid' },
  { value: 'unknown', label: 'Unknown' },
]

export const REMOTE_MODE_OPTIONS: { value: RemoteMode; label: string }[] = [
  { value: 'onsite', label: 'Onsite' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'remote', label: 'Remote' },
]

export const SECTOR_OPTIONS: { value: string; label: string }[] = [
  { value: 'prop_trading', label: 'Prop trading' },
  { value: 'hedge_fund', label: 'Hedge fund' },
  { value: 'bank', label: 'Bank' },
  { value: 'asset_manager', label: 'Asset manager' },
  { value: 'vendor', label: 'Vendor' },
  { value: 'crypto', label: 'Crypto' },
]

/** `unknown` is the majority case, not missing data (P4) — it never reads as "unknown". */
export const VISA_OPTIONS: { value: VisaStatus; label: string }[] = [
  { value: 'sponsors', label: 'Sponsors' },
  { value: 'unknown', label: 'Visa not mentioned' },
  { value: 'no', label: 'No sponsorship' },
]

export const TIER_OPTIONS: { value: Tier; label: string }[] = [
  { value: 'strong', label: 'Strong' },
  { value: 'possible', label: 'Possible' },
  { value: 'stretch', label: 'Stretch' },
  { value: 'rejected', label: 'Rejected' },
]

/** The application pipeline, in the order it happens. A posting with none of these is simply not tracked. */
export const STATUS_OPTIONS: { value: ApplicationStatus; label: string }[] = [
  { value: 'applied', label: 'Applied' },
  { value: 'interview', label: 'Interview' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected by them' },
  { value: 'withdrawn', label: 'Withdrawn' },
]

export const POSTED_WITHIN_OPTIONS: { value: number | null; label: string }[] = [
  { value: 1, label: 'Last 24h' },
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: null, label: 'All time' },
]
