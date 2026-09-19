import { describe, expect, it } from 'vitest'
import { DEFAULT_FILTER, DEFAULT_SORT, DEFAULT_TIERS, DEFAULT_VISA } from '@/features/filters/defaults'
import { decodeFeedState, encodeFeedState, type FeedUrlState } from '@/features/filters/url-codec'

function roundTrip(state: FeedUrlState): FeedUrlState {
  return decodeFeedState(encodeFeedState(state))
}

describe('decodeFeedState — defaults and tolerance', () => {
  it('decodes an empty URL to the full default state', () => {
    const state = decodeFeedState(new URLSearchParams(''))
    expect(state.filter).toEqual(DEFAULT_FILTER)
    expect(state.sort).toBe(DEFAULT_SORT)
  })

  it('checks sponsors and unknown by default when the visa param is absent', () => {
    const state = decodeFeedState(new URLSearchParams(''))
    expect(state.filter.visa).toEqual(DEFAULT_VISA)
    expect(state.filter.visa).toContain('sponsors')
    expect(state.filter.visa).toContain('unknown')
    expect(state.filter.visa).not.toContain('no')
  })

  it('excludes rejected from the default tier set', () => {
    const state = decodeFeedState(new URLSearchParams(''))
    expect(state.filter.tiers).toEqual(DEFAULT_TIERS)
    expect(state.filter.tiers).not.toContain('rejected')
  })

  it('ignores an unrecognized query parameter entirely', () => {
    const state = decodeFeedState(new URLSearchParams('utm_source=newsletter&countries=GB'))
    expect(state.filter.countries).toEqual(['GB'])
  })

  it('falls back to the default when every given visa value is invalid', () => {
    const state = decodeFeedState(new URLSearchParams('visa=bogus'))
    expect(state.filter.visa).toEqual(DEFAULT_VISA)
  })

  it('keeps a deliberate, narrower visa selection instead of defaulting', () => {
    const state = decodeFeedState(new URLSearchParams('visa=no'))
    expect(state.filter.visa).toEqual(['no'])
  })

  it('drops an invalid seniority but keeps the valid ones alongside it', () => {
    const state = decodeFeedState(new URLSearchParams('seniorities=graduate&seniorities=staff-plus-plus'))
    expect(state.filter.seniorities).toEqual(['graduate'])
  })

  it('falls back to score for an unknown sort key', () => {
    const state = decodeFeedState(new URLSearchParams('sort=alphabetical'))
    expect(state.sort).toBe('score')
  })

  it('clamps an out-of-range min_score instead of rejecting the URL', () => {
    expect(decodeFeedState(new URLSearchParams('min_score=250')).filter.min_score).toBe(100)
    expect(decodeFeedState(new URLSearchParams('min_score=not-a-number')).filter.min_score).toBe(0)
  })

  it('rejects a posted_within_days below 1 back to "all time"', () => {
    expect(decodeFeedState(new URLSearchParams('posted_within_days=0')).filter.posted_within_days).toBeNull()
    expect(decodeFeedState(new URLSearchParams('posted_within_days=7')).filter.posted_within_days).toBe(7)
  })

  it('treats an empty query string as no search', () => {
    expect(decodeFeedState(new URLSearchParams('query=')).filter.query).toBeNull()
  })
})

describe('encodeFeedState / decodeFeedState — round trip over all thirteen dimensions', () => {
  const fixtures: FeedUrlState[] = [
    { filter: DEFAULT_FILTER, sort: DEFAULT_SORT },
    { filter: { ...DEFAULT_FILTER, countries: ['GB', 'US'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, cities: ['London', 'Amsterdam'] }, sort: 'posted' },
    { filter: { ...DEFAULT_FILTER, companies: ['jane_street'] }, sort: 'company' },
    { filter: { ...DEFAULT_FILTER, sectors: ['prop_trading', 'hedge_fund'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, seniorities: ['graduate', 'junior'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, remote_modes: ['onsite'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, tech_all: ['cpp', 'python'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, tech_any: ['kdb', 'rust'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, visa: ['no'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, tiers: ['strong'] }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, min_score: 60 }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, posted_within_days: 7 }, sort: 'closes' },
    { filter: { ...DEFAULT_FILTER, query: 'quantitative developer' }, sort: 'score' },
    { filter: { ...DEFAULT_FILTER, favorites_only: true }, sort: 'seen' },
    {
      filter: {
        ...DEFAULT_FILTER,
        countries: ['GB', 'US'],
        tech_all: ['cpp'],
        seniorities: ['graduate'],
        visa: ['sponsors', 'unknown'],
      },
      sort: 'score',
    },
  ]

  it.each(fixtures)('is an identity for %j', (state) => {
    expect(roundTrip(state)).toEqual(state)
  })

  it('produces the shareable form from blueprint/wp/WP11-web-filters.md §2', () => {
    const state: FeedUrlState = {
      filter: { ...DEFAULT_FILTER, countries: ['GB', 'US'], tech_all: ['cpp'], seniorities: ['graduate'] },
      sort: 'score',
    }
    const params = encodeFeedState(state)
    expect(params.getAll('countries')).toEqual(['GB', 'US'])
    expect(params.get('tech_all')).toBe('cpp')
    expect(params.get('seniorities')).toBe('graduate')
    // visa/tiers/sort equal their defaults here, so they're omitted rather than spelled out —
    // decodeFeedState still reconstructs them, which is what the round-trip tests above check.
    expect(params.has('visa')).toBe(false)
    expect(params.has('sort')).toBe(false)
  })
})

describe('application statuses in the URL', () => {
  it('round-trips a tracking filter', () => {
    const state: FeedUrlState = {
      filter: { ...decodeFeedState(new URLSearchParams('')).filter, statuses: ['applied', 'interview'] },
      sort: 'score',
    }
    expect(roundTrip(state).filter.statuses).toEqual(['applied', 'interview'])
    expect(encodeFeedState(state).getAll('statuses')).toEqual(['applied', 'interview'])
  })

  it('drops a status it does not know instead of failing', () => {
    const state = decodeFeedState(new URLSearchParams('statuses=applied&statuses=ghosted'))
    expect(state.filter.statuses).toEqual(['applied'])
  })

  it('leaves the URL untouched when nothing is tracked', () => {
    expect(encodeFeedState(decodeFeedState(new URLSearchParams(''))).has('statuses')).toBe(false)
  })
})
