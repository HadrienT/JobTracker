import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { DEFAULT_FILTER, DEFAULT_VISA } from '@/features/filters/defaults'
import { useFeedUrlState } from '@/features/filters/use-feed-url-state'

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('useFeedUrlState', () => {
  it('reads the initial state from the current URL', () => {
    window.history.pushState(null, '', '/?countries=GB&sort=posted')
    const { result } = renderHook(() => useFeedUrlState())
    expect(result.current.filter.countries).toEqual(['GB'])
    expect(result.current.sort).toBe('posted')
  })

  it('setFilter merges the patch and pushes a new, shareable URL', () => {
    const { result } = renderHook(() => useFeedUrlState())
    act(() => {
      result.current.setFilter({ countries: ['GB', 'US'] })
    })
    expect(result.current.filter.countries).toEqual(['GB', 'US'])
    expect(result.current.filter.visa).toEqual(DEFAULT_VISA)
    expect(window.location.search).toContain('countries=GB')
  })

  it('setSort issues a new request key without touching the filter', () => {
    const { result } = renderHook(() => useFeedUrlState())
    act(() => {
      result.current.setFilter({ companies: ['jane_street'] })
    })
    act(() => {
      result.current.setSort('posted')
    })
    expect(result.current.sort).toBe('posted')
    expect(result.current.filter.companies).toEqual(['jane_street'])
  })

  it('resetFilters returns to the defaults, not to empty', () => {
    const { result } = renderHook(() => useFeedUrlState())
    act(() => {
      result.current.setFilter({ visa: ['no'], countries: ['GB'] })
    })
    act(() => {
      result.current.resetFilters()
    })
    expect(result.current.filter).toEqual(DEFAULT_FILTER)
    expect(result.current.filter.visa).toEqual(DEFAULT_VISA)
  })

  it('re-syncs from the URL on a browser Back/Forward navigation (popstate)', () => {
    const { result } = renderHook(() => useFeedUrlState())
    act(() => {
      result.current.setFilter({ countries: ['GB'] })
    })
    act(() => {
      result.current.setFilter({ countries: ['GB', 'US'], companies: ['jane_street'] })
    })
    expect(result.current.filter.companies).toEqual(['jane_street'])

    // Simulate the browser restoring the previous history entry's URL and
    // firing popstate — this is the same signal `history.back()` sends.
    act(() => {
      window.history.pushState(null, '', '/?countries=GB&countries=US')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })

    expect(result.current.filter.countries).toEqual(['GB', 'US'])
    expect(result.current.filter.companies).toEqual([])
  })

  it('reloading a filtered URL yields the same screen and the same sort', () => {
    window.history.pushState(null, '', '/?countries=GB&tech_all=cpp&seniorities=graduate&sort=posted')
    const { result, unmount } = renderHook(() => useFeedUrlState())
    const before = { filter: result.current.filter, sort: result.current.sort }
    unmount()

    const { result: reloaded } = renderHook(() => useFeedUrlState())
    expect(reloaded.current.filter).toEqual(before.filter)
    expect(reloaded.current.sort).toEqual(before.sort)
  })
})
