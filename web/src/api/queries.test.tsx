import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { postingsQueryKey, useSetFavorite, useSetHidden, usePostingsFeed } from '@/api/queries'
import { server } from '@/mocks/server'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('usePostingsFeed', () => {
  it('paginates across 5 pages with no duplicated or skipped posting', async () => {
    const { result } = renderHook(() => usePostingsFeed({}, 'score'), { wrapper })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    for (let page = 0; page < 4; page++) {
      await waitFor(() => {
        expect(result.current.hasNextPage).toBe(true)
      })
      await result.current.fetchNextPage()
      await waitFor(() => {
        expect(result.current.isFetchingNextPage).toBe(false)
      })
    }

    const ids = result.current.data?.pages.flatMap((page) => page.items.map((item) => item.posting_id)) ?? []
    expect(ids).toHaveLength(250)
    expect(new Set(ids).size).toBe(250)
  })

  it('keys the cache on sort as well as filter — changing sort is a new request', () => {
    const scoreKey = postingsQueryKey({}, 'score')
    const postedKey = postingsQueryKey({}, 'posted')
    expect(scoreKey).not.toEqual(postedKey)

    const withFilterKey = postingsQueryKey({ query: 'quant' }, 'score')
    expect(withFilterKey).not.toEqual(scoreKey)
  })

  it('surfaces a fetch-next-page error while keeping already-loaded pages', async () => {
    const { result } = renderHook(() => usePostingsFeed({}, 'score'), { wrapper })
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    const firstPageIds = result.current.data?.pages[0]?.items.map((i) => i.posting_id) ?? []

    server.use(http.get('*/postings', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    await result.current.fetchNextPage()

    await waitFor(() => {
      expect(result.current.isFetchNextPageError).toBe(true)
    })
    const stillFirstPageIds = result.current.data?.pages[0]?.items.map((i) => i.posting_id) ?? []
    expect(stillFirstPageIds).toEqual(firstPageIds)
  })
})

describe('optimistic favorite/hide mutations', () => {
  it('flips favorited in the cache once the request succeeds', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const localWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result: feed } = renderHook(() => usePostingsFeed({}, 'score'), { wrapper: localWrapper })
    await waitFor(() => {
      expect(feed.current.isSuccess).toBe(true)
    })
    const target = feed.current.data?.pages[0]?.items[0]
    if (!target) throw new Error('no posting in fixture page')

    const { result: mutation } = renderHook(() => useSetFavorite(), { wrapper: localWrapper })
    mutation.current.mutate({ postingId: target.posting_id, value: !target.favorited })

    await waitFor(() => {
      expect(mutation.current.isSuccess).toBe(true)
    })
    const cached = queryClient
      .getQueryData<{ pages: { items: { posting_id: string; favorited: boolean }[] }[] }>(postingsQueryKey({}, 'score'))
      ?.pages[0]?.items.find((i) => i.posting_id === target.posting_id)
    expect(cached?.favorited).toBe(!target.favorited)
  })

  it('rolls the optimistic update back when the request fails', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const localWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result: feed } = renderHook(() => usePostingsFeed({}, 'score'), { wrapper: localWrapper })
    await waitFor(() => {
      expect(feed.current.isSuccess).toBe(true)
    })
    const target = feed.current.data?.pages[0]?.items[0]
    if (!target) throw new Error('no posting in fixture page')

    server.use(http.post('*/postings/:id/favorite', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    const { result: mutation } = renderHook(() => useSetFavorite(), { wrapper: localWrapper })
    mutation.current.mutate({ postingId: target.posting_id, value: !target.favorited })

    await waitFor(() => {
      expect(mutation.current.isError).toBe(true)
    })
    const cachedAfterRollback = queryClient
      .getQueryData<{ pages: { items: { posting_id: string; favorited: boolean }[] }[] }>(postingsQueryKey({}, 'score'))
      ?.pages[0]?.items.find((i) => i.posting_id === target.posting_id)
    expect(cachedAfterRollback?.favorited).toBe(target.favorited)
  })

  it('removes a hidden posting from the cached feed pages', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const localWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result: feed } = renderHook(() => usePostingsFeed({}, 'score'), { wrapper: localWrapper })
    await waitFor(() => {
      expect(feed.current.isSuccess).toBe(true)
    })
    const target = feed.current.data?.pages[0]?.items[0]
    if (!target) throw new Error('no posting in fixture page')

    const { result: mutation } = renderHook(() => useSetHidden(), { wrapper: localWrapper })
    mutation.current.mutate({ postingId: target.posting_id, value: true })

    await waitFor(() => {
      const cached = queryClient
        .getQueryData<{ pages: { items: { posting_id: string }[] }[] }>(postingsQueryKey({}, 'score'))
        ?.pages[0]?.items.some((i) => i.posting_id === target.posting_id)
      expect(cached).toBe(false)
    })
  })
})
