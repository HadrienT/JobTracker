import { describe, expect, it } from 'vitest'
import type { ApplicationOut } from '@/api/queries'
import {
  answerDelay,
  applicationStats,
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
    ...overrides,
  }
}

const OPEN = application({
  application_id: 'open',
  company: 'Société Générale',
})
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
      filterApplications(ALL, { view, query: '', year: null }).map((a) => a.application_id)
    expect(ids('open')).toEqual(['open'])
    expect(ids('abandoned')).toEqual(['old'])
    expect(ids('interviews')).toEqual(['rejected'])
    expect(ids('rejected')).toEqual(['rejected', 'quick'])
    expect(ids('all')).toHaveLength(4)
  })

  it('search ignores case and accents; year narrows on the application date', () => {
    expect(filterApplications(ALL, { view: 'all', query: 'societe', year: null })).toEqual([OPEN])
    expect(filterApplications(ALL, { view: 'all', query: '', year: 2024 })).toEqual([OLD])
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

  it('years, newest first; today in the local calendar', () => {
    expect(yearsOf(ALL)).toEqual([2026, 2024])
    expect(todayIso(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})
