import { describe, expect, it } from 'vitest'
import type { ApplicationOut, CvOut } from '@/api/queries'
import {
  answerDelay,
  applicationStats,
  countryCounts,
  cvStats,
  filterApplications,
  sortApplications,
  todayIso,
  yearsOf,
} from '@/features/applications/model'

function application(overrides: Partial<ApplicationOut> & Pick<ApplicationOut, 'application_id'>): ApplicationOut {
  return {
    company: 'Acme',
    company_slug: null,
    title: 'Quant Dev',
    location: 'UK (London)',
    applied_on: '2026-10-01',
    applied_on_estimated: false,
    closed_on: null,
    status: 'applied',
    reason: '',
    posting_id: null,
    origin: 'import',
    note: '',
    open: true,
    abandoned: false,
    last_news_on: '2026-10-01',
    reached_interview: false,
    countries: ['GB'],
    cv_id: null,
    cv_source: null,
    ...overrides,
  }
}

const OPEN = application({ application_id: 'open', company: 'Société Générale', countries: ['CH'] })
const OLD = application({
  application_id: 'old',
  applied_on: '2024-11-15',
  open: false,
  abandoned: true,
})
const REJECTED = application({
  application_id: 'rejected',
  company: 'Borealis',
  applied_on: '2026-09-01',
  closed_on: '2026-09-21',
  status: 'rejected',
  open: false,
  reached_interview: true,
})
const QUICK_NO = application({
  application_id: 'quick',
  applied_on: '2026-09-01',
  closed_on: '2026-09-03',
  status: 'rejected',
  open: false,
})
const ALL = [OPEN, OLD, REJECTED, QUICK_NO]

describe('applications model', () => {
  it('views follow what the API derived — open excludes the abandoned', () => {
    const ids = (view: Parameters<typeof filterApplications>[1]['view']) =>
      filterApplications(ALL, { view, query: '', year: null, country: null, noCv: false }).map((a) => a.application_id)
    expect(ids('open')).toEqual(['open'])
    expect(ids('abandoned')).toEqual(['old'])
    expect(ids('interviews')).toEqual(['rejected'])
    expect(ids('rejected')).toEqual(['rejected', 'quick'])
    expect(ids('all')).toHaveLength(4)
  })

  it('search ignores case and accents; year narrows on the application date', () => {
    expect(filterApplications(ALL, { view: 'all', query: 'societe', year: null, country: null, noCv: false })).toEqual([OPEN])
    expect(filterApplications(ALL, { view: 'all', query: '', year: 2024, country: null, noCv: false })).toEqual([OLD])
  })

  it('answer delay: days to the answer, or days spent waiting', () => {
    expect(answerDelay(REJECTED, '2026-10-21')).toEqual({
      days: 20,
      waiting: false,
    })
    expect(answerDelay(OPEN, '2026-10-21')).toEqual({
      days: 20,
      waiting: true,
    })
  })

  it('sorts by any column, ties broken by id', () => {
    const byDate = sortApplications(ALL, 'applied', true, '2026-10-21').map((a) => a.application_id)
    expect(byDate).toEqual(['open', 'rejected', 'quick', 'old'])
    const byCompany = sortApplications(ALL, 'company', false, '2026-10-21').map((a) => a.company)
    expect(byCompany[0]).toBe('Acme')
  })

  it('stats: response rate over every application, median time to a rejection', () => {
    const stats = applicationStats(ALL)
    expect(stats).toMatchObject({
      total: 4,
      open: 1,
      abandoned: 1,
      interviews: 1,
      rejected: 2,
    })
    expect(stats.responseRate).toBe(0.5)
    expect(stats.medianDaysToRejection).toBe(11)
    expect(applicationStats([]).responseRate).toBeNull()
  })

  it('countries: counted most first, and filtered on', () => {
    expect(countryCounts(ALL)).toEqual([
      { code: 'GB', count: 3 },
      { code: 'CH', count: 1 },
    ])
    expect(filterApplications(ALL, { view: 'all', query: '', year: null, country: 'CH', noCv: false })).toEqual([OPEN])
  })

  it('years, newest first; today in the local calendar', () => {
    expect(yearsOf(ALL)).toEqual([2026, 2024])
    expect(todayIso(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})

describe('CVs', () => {
  const cv = (cvId: string, pinned: boolean): CvOut => ({
    cv_id: cvId,
    label: cvId,
    file_name: `${cvId}.pdf`,
    size: 1,
    pinned,
    created_at: '2026-10-01T00:00:00Z',
    applications: 0,
    current: false,
  })
  const SENT = [
    application({ application_id: 'a', cv_id: 'v1', cv_source: 'confirmed', status: 'rejected' }),
    application({ application_id: 'b', cv_id: 'v1', cv_source: 'inferred', reached_interview: true }),
    application({ application_id: 'c', cv_id: 'v1', cv_source: 'inferred' }),
    application({ application_id: 'd', cv_id: 'v1', cv_source: 'confirmed' }),
    application({ application_id: 'e', cv_id: 'tailored', cv_source: 'confirmed' }),
    application({ application_id: 'f' }),
  ]

  it('finds what is left to fill in', () => {
    const missing = filterApplications(SENT, { view: 'all', query: '', year: null, country: null, noCv: true })
    expect(missing.map((a) => a.application_id)).toEqual(['f'])
  })

  it('tells what became of each version, and how much of it is assumed', () => {
    const [v1, ...others] = cvStats([cv('v1', true), cv('tailored', false), cv('unused', true)], SENT)
    expect(others).toEqual([])
    expect(v1).toMatchObject({ sent: 4, inferred: 2, interviews: 1, responseRate: 0.5 })
  })
})
