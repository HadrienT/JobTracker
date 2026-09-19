import { monotonicFactory } from 'ulid'
import type {
  Compensation,
  CompanyOut,
  HealthSnapshot,
  Location,
  PostingDetailOut,
  PostingOut,
  Reason,
  RemoteMode,
  RoleFamily,
  Seniority,
  Source,
  Tier,
  VisaStatus,
} from './contract'

/** Deterministic PRNG (mulberry32) — the fixture set must be stable across runs. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const rand = mulberry32(20260917)
const ulid = monotonicFactory(() => rand())

function pick<T>(pool: readonly T[]): T {
  const item = pool[Math.floor(rand() * pool.length)]
  if (item === undefined) throw new Error('empty pool')
  return item
}

function pickSome<T>(pool: readonly T[], min: number, max: number): T[] {
  const n = Math.min(pool.length, min + Math.floor(rand() * (max - min + 1)))
  const shuffled = [...pool].sort(() => rand() - 0.5)
  return shuffled.slice(0, n)
}

function daysAgo(days: number): string {
  const d = new Date('2026-09-17T09:00:00Z')
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString()
}

const COMPANIES: { slug: string; name: string; sector: string; country: string }[] = [
  { slug: 'jane_street', name: 'Jane Street', sector: 'prop_trading', country: 'US' },
  { slug: 'optiver', name: 'Optiver', sector: 'prop_trading', country: 'NL' },
  { slug: 'imc_trading', name: 'IMC Trading', sector: 'prop_trading', country: 'NL' },
  { slug: 'two_sigma', name: 'Two Sigma', sector: 'hedge_fund', country: 'US' },
  { slug: 'citadel', name: 'Citadel', sector: 'hedge_fund', country: 'US' },
  { slug: 'akuna_capital', name: 'Akuna Capital', sector: 'prop_trading', country: 'US' },
  { slug: 'susquehanna', name: 'Susquehanna (SIG)', sector: 'prop_trading', country: 'US' },
  { slug: 'gsa_capital', name: 'GSA Capital', sector: 'hedge_fund', country: 'GB' },
  { slug: 'man_group', name: 'Man Group', sector: 'asset_manager', country: 'GB' },
  { slug: 'bnp_paribas', name: 'BNP Paribas', sector: 'bank', country: 'FR' },
  { slug: 'goldman_sachs', name: 'Goldman Sachs', sector: 'bank', country: 'US' },
  { slug: 'hudson_river_trading', name: 'Hudson River Trading', sector: 'prop_trading', country: 'US' },
  { slug: 'qube_research', name: 'Qube Research & Technologies', sector: 'hedge_fund', country: 'GB' },
  { slug: 'kx_systems', name: 'KX Systems', sector: 'vendor', country: 'IE' },
  { slug: 'wintermute', name: 'Wintermute', sector: 'crypto', country: 'GB' },
]

const ROLE_TITLES: { title: string; family: RoleFamily }[] = [
  { title: 'Quantitative Developer', family: 'quant_dev' },
  { title: 'Quantitative Developer (C++)', family: 'quant_dev' },
  { title: 'Graduate Quantitative Developer', family: 'quant_dev' },
  { title: 'Quantitative Researcher', family: 'quant_research' },
  { title: 'Quantitative Trader', family: 'quant_trading' },
  { title: 'Software Engineer, Trading Systems', family: 'swe_platform' },
  { title: 'Data Engineer, Market Data', family: 'data_eng' },
  { title: 'Risk Analyst, Quantitative Risk', family: 'risk' },
  {
    title:
      'Senior Staff Quantitative Developer — Core Trading Infrastructure & Market Data Platform (Multiple Locations, Hybrid, 2026 Start, req-88213)',
    family: 'quant_dev',
  },
]

const SENIORITIES: Seniority[] = ['intern', 'graduate', 'junior', 'mid', 'senior', 'lead', 'unknown']
const TECH_POOL = ['cpp', 'python', 'rust', 'kdb', 'java', 'go', 'sql', 'linux', 'fpga']
const CITIES: { city: string; country: string; region: Location['region'] }[] = [
  { city: 'Amsterdam', country: 'NL', region: 'emea' },
  { city: 'London', country: 'GB', region: 'emea' },
  { city: 'Paris', country: 'FR', region: 'emea' },
  { city: 'New York', country: 'US', region: 'amer' },
  { city: 'Chicago', country: 'US', region: 'amer' },
  { city: 'Singapore', country: 'SG', region: 'apac' },
  { city: 'Hong Kong', country: 'HK', region: 'apac' },
  { city: 'Dublin', country: 'IE', region: 'emea' },
]
const REMOTE_MODES: RemoteMode[] = ['onsite', 'hybrid', 'remote', 'unknown']
const VISA_STATUSES: VisaStatus[] = ['sponsors', 'no', 'unknown']
const SOURCES: Source[] = ['greenhouse', 'lever', 'ashby', 'workday', 'smartrecruiters']
const REASON_CATALOG: Reason[] = [
  { code: 'title_match', delta: 25, evidence: 'Quantitative Developer' },
  { code: 'target_seniority', delta: 15, evidence: '0-2 years of experience' },
  { code: 'stack_match', delta: 10, evidence: 'C++, Python' },
  { code: 'senior_only', delta: -30, evidence: '8+ years required' },
  { code: 'phd_required', delta: -20, evidence: 'PhD in a quantitative field' },
  { code: 'no_sponsorship', delta: -15, evidence: 'must be authorized to work without sponsorship' },
]

function tierForScore(score: number): Tier {
  if (score >= 70) return 'strong'
  if (score >= 45) return 'possible'
  if (score >= 20) return 'stretch'
  return 'rejected'
}

function buildLocations(): Location[] {
  const unresolved = rand() < 0.05
  if (unresolved) {
    return [
      {
        city: null,
        country: null,
        region: null,
        remote_mode: 'unknown',
        raw: pick(['Multiple EMEA locations', 'See job description for site', 'TBD']),
      },
    ]
  }
  const mode = pick(REMOTE_MODES)
  const sites = pickSome(CITIES, 1, rand() < 0.15 ? 4 : 1)
  return sites.map((site) => ({
    city: site.city,
    country: site.country,
    region: site.region,
    remote_mode: mode,
    raw: `${site.city}, ${site.country}`,
  }))
}

function buildCompensation(country: string): Compensation {
  if (rand() < 0.35) {
    return {
      amount_min: null,
      amount_max: null,
      currency: null,
      period: null,
      bonus_mentioned: rand() < 0.3,
      equity_mentioned: rand() < 0.1,
      raw: null,
    }
  }
  const currency = { US: 'USD', GB: 'GBP', NL: 'EUR', FR: 'EUR', IE: 'EUR', SG: 'SGD', HK: 'HKD' }[country] ?? 'USD'
  const base = 60000 + Math.floor(rand() * 120000)
  const spread = 10000 + Math.floor(rand() * 40000)
  return {
    amount_min: String(base),
    amount_max: String(base + spread),
    currency,
    period: 'year',
    bonus_mentioned: rand() < 0.5,
    equity_mentioned: rand() < 0.15,
    raw: null,
  }
}

function buildOne(index: number): PostingDetailOut {
  const company = pick(COMPANIES)
  const role = pick(ROLE_TITLES)
  const seniority = pick(SENIORITIES)
  const score = Math.floor(rand() * 101)
  const tier = tierForScore(score)
  const reasons = pickSome(REASON_CATALOG, 1, 3)
  const postedDaysAgo = Math.floor(rand() * 60)
  const firstSeenDaysAgo = Math.max(0, postedDaysAgo - Math.floor(rand() * 3))
  const hasPostedAt = rand() < 0.85
  const hasClosesAt = rand() < 0.3

  return {
    posting_id: ulid(),
    title: role.title.length > 80 ? `${role.title.slice(0, 77)}...` : role.title,
    title_raw: role.title,
    company_slug: company.slug,
    company_name: company.name,
    sector: company.sector,
    source: pick(SOURCES),
    role_family: role.family,
    seniority,
    min_years: seniority === 'unknown' || rand() < 0.2 ? null : Math.floor(rand() * 6),
    phd_required: rand() < 0.08,
    locations: buildLocations(),
    compensation: buildCompensation(company.country),
    visa_sponsorship: pick(VISA_STATUSES),
    tech: pickSome(TECH_POOL, 1, 4),
    posted_at: hasPostedAt ? daysAgo(postedDaysAgo) : null,
    first_seen_at: daysAgo(firstSeenDaysAgo),
    last_seen_at: daysAgo(Math.floor(rand() * firstSeenDaysAgo)),
    closes_at: hasClosesAt ? daysAgo(-Math.floor(rand() * 21)) : null,
    score,
    tier,
    alias_count: rand() < 0.2 ? Math.ceil(rand() * 3) : 0,
    favorited: rand() < 0.05,
    hidden: false,
    application_status: null,
    note: '',
    url: `https://boards.example.com/${company.slug}/jobs/${String(index)}`,
    description: `We are looking for a ${role.title} to join ${company.name}. ${'Lorem ipsum dolor sit amet, consectetur adipiscing elit. '.repeat(6)}`,
    reasons,
    rejection_reason: tier === 'rejected' ? pick(['senior_only', 'phd_required', 'not_quant']) : null,
    aliases: [],
  }
}

const FIXTURE_SIZE = 2000

export const POSTINGS: PostingDetailOut[] = Array.from({ length: FIXTURE_SIZE }, (_, i) => buildOne(i))

export function toListItem(posting: PostingDetailOut): PostingOut {
  return {
    posting_id: posting.posting_id,
    title: posting.title,
    title_raw: posting.title_raw,
    company_slug: posting.company_slug,
    company_name: posting.company_name,
    sector: posting.sector,
    source: posting.source,
    role_family: posting.role_family,
    seniority: posting.seniority,
    min_years: posting.min_years,
    phd_required: posting.phd_required,
    locations: posting.locations,
    compensation: posting.compensation,
    visa_sponsorship: posting.visa_sponsorship,
    tech: posting.tech,
    posted_at: posting.posted_at,
    first_seen_at: posting.first_seen_at,
    last_seen_at: posting.last_seen_at,
    closes_at: posting.closes_at,
    score: posting.score,
    tier: posting.tier,
    alias_count: posting.alias_count,
    favorited: posting.favorited,
    hidden: posting.hidden,
    application_status: posting.application_status,
    url: posting.url,
  }
}

export const COMPANIES_OUT: CompanyOut[] = COMPANIES.map((company) => ({
  company_slug: company.slug,
  company_name: company.name,
  sector: company.sector,
  hq_country: company.country,
  source: pick(SOURCES),
  enabled: rand() < 0.95,
  last_ok_at: rand() < 0.9 ? daysAgo(Math.floor(rand() * 3)) : null,
  postings_count: POSTINGS.filter((p) => p.company_slug === company.slug).length,
}))

export const HEALTH: HealthSnapshot = {
  schema_version: 1,
  feed: {
    active_postings: POSTINGS.length,
    newest_posting_age_h: 4,
    stale: false,
  },
  alerts: [],
  sources: SOURCES.map((source) => ({
    source,
    status: rand() < 0.9 ? 'ok' : 'degraded',
    last_run_at: daysAgo(Math.floor(rand() * 2)),
    last_count: Math.floor(rand() * 200),
    boards_ok: Math.floor(rand() * 50),
    boards_error: rand() < 0.1 ? Math.ceil(rand() * 3) : 0,
    alert: null,
  })),
}
