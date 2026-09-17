/**
 * Provisional wire contract for the seven routes of blueprint/03-INTERFACES.md §3.6.
 *
 * This is hand-written, not generated: WP07 has not shipped `web/openapi.json` yet.
 * The day it does, `just types` regenerates `src/api/schema.gen.ts` and this file
 * is replaced — see blueprint/wp/WP09-web-foundations.md's framing note. Until
 * then, MSW serves this shape so WP10/WP11 can build against a stable contract.
 */

export type Source =
  | 'greenhouse'
  | 'lever'
  | 'ashby'
  | 'smartrecruiters'
  | 'workable'
  | 'recruitee'
  | 'personio'
  | 'workday'
  | 'custom'
  | 'efinancialcareers'
  | 'wttj'
  | 'linkedin'
  | 'indeed'

export type RoleFamily =
  | 'quant_dev'
  | 'quant_research'
  | 'quant_trading'
  | 'swe_platform'
  | 'data_eng'
  | 'risk'
  | 'other'

export type Seniority = 'intern' | 'graduate' | 'junior' | 'mid' | 'senior' | 'lead' | 'unknown'

export type VisaStatus = 'sponsors' | 'no' | 'unknown'

export type RemoteMode = 'onsite' | 'hybrid' | 'remote' | 'unknown'

export type SalaryPeriod = 'year' | 'month' | 'day' | 'hour'

export type Tier = 'strong' | 'possible' | 'stretch' | 'rejected'

export type SortKey = 'score' | 'posted' | 'seen' | 'company' | 'closes'

export interface Location {
  city: string | null
  country: string | null
  region: 'emea' | 'amer' | 'apac' | null
  remote_mode: RemoteMode
  raw: string | null
}

export interface Compensation {
  amount_min: string | null
  amount_max: string | null
  currency: string | null
  period: SalaryPeriod | null
  bonus_mentioned: boolean
  equity_mentioned: boolean
  raw: string | null
}

export interface Reason {
  code: string
  delta: number
  evidence: string | null
}

export interface Alias {
  source: Source
  url: string
}

export interface PostingOut {
  posting_id: string
  title: string
  title_raw: string
  company_slug: string
  company_name: string
  sector: string
  source: Source
  role_family: RoleFamily
  seniority: Seniority
  min_years: number | null
  phd_required: boolean
  locations: Location[]
  compensation: Compensation
  visa_sponsorship: VisaStatus
  tech: string[]
  posted_at: string | null
  first_seen_at: string
  last_seen_at: string
  closes_at: string | null
  score: number
  tier: Tier
  alias_count: number
  favorited: boolean
  hidden: boolean
  url: string
}

export interface PostingDetailOut extends PostingOut {
  description: string
  reasons: Reason[]
  rejection_reason: string | null
  aliases: Alias[]
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface FacetBucket {
  value: string
  label: string
  count: number
}

export interface FacetCounts {
  countries: FacetBucket[]
  cities: FacetBucket[]
  companies: FacetBucket[]
  sectors: FacetBucket[]
  role_families: FacetBucket[]
  seniorities: FacetBucket[]
  remote_modes: FacetBucket[]
  tech: FacetBucket[]
  visa: FacetBucket[]
  tiers: FacetBucket[]
}

export type SourceHealthStatus = 'ok' | 'degraded' | 'down'

export interface CompanyOut {
  company_slug: string
  company_name: string
  sector: string
  hq_country: string
  postings_count: number
  last_successful_collect_at: string | null
  status: SourceHealthStatus
}

export interface HealthSourceStatus {
  source: Source
  status: SourceHealthStatus
  last_success_at: string | null
  consecutive_failures: number
}

export interface HealthOut {
  sources: HealthSourceStatus[]
  feed_stale: boolean
  oldest_fresh_run_at: string | null
  schema_version: number
}

export const STALE_AFTER_DAYS = 30
