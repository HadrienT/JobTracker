import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isNewSinceLastVisit, previousVisit, resetPreviousVisitForTests } from '@/features/feed/last-visit'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  resetPreviousVisitForTests()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('previousVisit', () => {
  it('is null on the very first visit, so nothing is flagged as new', () => {
    expect(previousVisit()).toBeNull()
    expect(isNewSinceLastVisit('2099-01-01T00:00:00Z')).toBe(false)
  })

  it('remembers the moment of the previous visit for the next tab session', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-01T10:00:00Z'))
    previousVisit() // first visit: stamps "now" for next time

    sessionStorage.clear() // a new tab session
    resetPreviousVisitForTests()
    vi.setSystemTime(new Date('2026-09-05T10:00:00Z'))

    expect(previousVisit()).toBe('2026-09-01T10:00:00.000Z')
  })

  it('does not move on a reload inside the same session', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-01T10:00:00Z'))
    previousVisit()
    sessionStorage.clear()
    resetPreviousVisitForTests()
    vi.setSystemTime(new Date('2026-09-05T10:00:00Z'))
    const first = previousVisit()

    resetPreviousVisitForTests() // a reload: same tab, sessionStorage kept
    vi.setSystemTime(new Date('2026-09-05T10:30:00Z'))

    expect(previousVisit()).toBe(first)
    expect(first).toBe('2026-09-01T10:00:00.000Z')
  })

  it('flags only what was first seen after the previous visit', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-01T10:00:00Z'))
    previousVisit()
    sessionStorage.clear()
    resetPreviousVisitForTests()
    vi.setSystemTime(new Date('2026-09-05T10:00:00Z'))

    expect(isNewSinceLastVisit('2026-09-03T00:00:00+00:00')).toBe(true)
    expect(isNewSinceLastVisit('2026-08-30T00:00:00+00:00')).toBe(false)
  })

  it('survives storage being unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(previousVisit()).toBeNull()
    vi.restoreAllMocks()
  })
})
