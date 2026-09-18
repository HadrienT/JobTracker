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
