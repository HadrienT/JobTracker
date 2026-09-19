import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { usePostingRoute } from '@/features/feed/routing'

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('usePostingRoute', () => {
  it('reads the posting id already in the URL on mount', () => {
    window.history.pushState(null, '', '/p/abc123')
    const { result } = renderHook(() => usePostingRoute())
    expect(result.current.postingId).toBe('abc123')
  })

  it('starts with no posting selected on the feed root', () => {
    const { result } = renderHook(() => usePostingRoute())
    expect(result.current.postingId).toBeNull()
  })

  it('openPosting pushes a real, shareable URL', () => {
    const { result } = renderHook(() => usePostingRoute())
    act(() => {
      result.current.openPosting('xyz')
    })
    expect(result.current.postingId).toBe('xyz')
    expect(window.location.pathname).toBe('/p/xyz')
  })

  it('closePosting returns to the feed root', () => {
    const { result } = renderHook(() => usePostingRoute())
    act(() => {
      result.current.openPosting('xyz')
    })
    act(() => {
      result.current.closePosting()
    })
    expect(result.current.postingId).toBeNull()
    expect(window.location.pathname).toBe('/')
  })

  it('keeps the filters and sort in the query string when opening and closing a detail', () => {
    window.history.pushState(null, '', '/?countries=US&sort=seen')
    const { result } = renderHook(() => usePostingRoute())
    act(() => {
      result.current.openPosting('xyz')
    })
    expect(window.location.pathname).toBe('/p/xyz')
    expect(window.location.search).toBe('?countries=US&sort=seen')
    act(() => {
      result.current.closePosting()
    })
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toBe('?countries=US&sort=seen')
  })

  it('sits on the map when given its base path: /map/p/{id} in, /map out', () => {
    window.history.pushState(null, '', '/map?countries=US')
    const { result } = renderHook(() => usePostingRoute('/map'))
    expect(result.current.postingId).toBeNull()
    act(() => {
      result.current.openPosting('xyz')
    })
    expect(window.location.pathname).toBe('/map/p/xyz')
    expect(window.location.search).toBe('?countries=US')
    act(() => {
      result.current.closePosting()
    })
    expect(window.location.pathname).toBe('/map')
    expect(window.location.search).toBe('?countries=US')
  })

  it('reads a map detail URL on mount, and ignores a feed detail URL', () => {
    window.history.pushState(null, '', '/map/p/abc')
    expect(renderHook(() => usePostingRoute('/map')).result.current.postingId).toBe('abc')
    expect(renderHook(() => usePostingRoute()).result.current.postingId).toBeNull()
  })

  it('follows browser back/forward navigation', () => {
    const { result } = renderHook(() => usePostingRoute())
    act(() => {
      result.current.openPosting('xyz')
    })
    act(() => {
      window.history.pushState(null, '', '/')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(result.current.postingId).toBeNull()
  })
})
