import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useAppRoute } from '@/app/routes'

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('useAppRoute', () => {
  it('resolves to feed for the root path and unknown paths alike', () => {
    window.history.pushState(null, '', '/p/abc123')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('feed')
  })

  it('resolves /applications and its detail URLs to the Applications tab', () => {
    window.history.pushState(null, '', '/applications')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('applications')
    window.history.pushState(null, '', '/applications/p/01ABC')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('applications')
  })

  it('resolves /map and its detail URLs to the map, not the feed', () => {
    window.history.pushState(null, '', '/map')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('map')
    window.history.pushState(null, '', '/map/p/abc')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('map')
  })

  it('resolves /ch and its detail URLs to the Swiss tech feed — and nothing that merely starts with ch', () => {
    window.history.pushState(null, '', '/ch')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('swiss')
    window.history.pushState(null, '', '/ch/p/abc')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('swiss')
    window.history.pushState(null, '', '/chart')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('feed')
  })

  it('resolves /companies and /health', () => {
    window.history.pushState(null, '', '/companies')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('companies')
    window.history.pushState(null, '', '/health')
    expect(renderHook(() => useAppRoute()).result.current.route).toBe('health')
  })

  it('navigate() pushes a URL and updates the route', () => {
    const { result } = renderHook(() => useAppRoute())
    act(() => {
      result.current.navigate('/companies')
    })
    expect(result.current.route).toBe('companies')
    expect(window.location.pathname).toBe('/companies')
  })

  it('follows browser Back/Forward navigation', () => {
    const { result } = renderHook(() => useAppRoute())
    act(() => {
      result.current.navigate('/health')
    })
    act(() => {
      window.history.pushState(null, '', '/')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(result.current.route).toBe('feed')
  })
})
