/**
 * TanStack Query hooks — the only place `features/feed` talks to the API.
 * Cache keys include both the filter and the sort key (blueprint/wp/WP10-web-feed.md
 * §2-3): changing sort is a new request, never a client-side re-sort of 15 000 rows.
 */
import { type InfiniteData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type CompaniesQuery, type PostingsQuery } from '@/api/client'
import type { components } from '@/api/schema.gen'

type Schemas = components['schemas']
export type PostingsFilter = Omit<PostingsQuery, 'sort' | 'cursor' | 'limit'>
export type SortKey = Schemas['SortKey']
type PostingsPage = Schemas['PostingsPage']
type PostingOut = Schemas['PostingOut']
type PostingDetailOut = Schemas['PostingDetailOut']

const PAGE_SIZE = 50
const POSTINGS_ROOT_KEY = 'postings' as const

export function postingsQueryKey(filter: PostingsFilter, sort: SortKey) {
  return [POSTINGS_ROOT_KEY, filter, sort] as const
}

export function usePostingsFeed(filter: PostingsFilter, sort: SortKey) {
  return useInfiniteQuery({
    queryKey: postingsQueryKey(filter, sort),
    queryFn: ({ pageParam }) => api.listPostings({ ...filter, sort, cursor: pageParam, limit: PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  })
}

/** One pin per located city, under the same filters as the feed — `placeholderData` keeps the map steady while a filter moves. */
export function useMapPins(filter: PostingsFilter) {
  return useQuery({
    queryKey: ['map-pins', filter] as const,
    queryFn: () => api.getMapPins(filter),
    placeholderData: (previous) => previous,
  })
}

/** The postings behind one pin: the feed's own route, narrowed to a single `(country, city)`. */
export function usePinPostings(filter: PostingsFilter, place: { country: string; city: string } | null) {
  return useInfiniteQuery({
    queryKey: [POSTINGS_ROOT_KEY, 'pin', filter, place] as const,
    queryFn: ({ pageParam }) => {
      if (place === null) throw new Error('usePinPostings: queryFn ran without a place')
      return api.listPostings({
        ...filter,
        place_country: place.country,
        place_city: place.city,
        sort: 'score',
        cursor: pageParam,
        limit: PAGE_SIZE,
      })
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: place !== null,
  })
}

/** Counts for the filter panel — kept alive across a filter change so checkboxes don't flash to zero mid-request. */
export function useFacets(filter: PostingsFilter) {
  return useQuery({
    queryKey: ['facets', filter] as const,
    queryFn: () => api.getFacets(filter),
    placeholderData: (previous) => previous,
  })
}

export function useCompanies(query: CompaniesQuery = {}) {
  return useQuery({
    queryKey: ['companies', query] as const,
    queryFn: () => api.getCompanies(query),
  })
}

const HEALTH_POLL_INTERVAL_MS = 60_000

/** Polled so a stale-feed banner (blueprint/wp/WP11-web-filters.md §5) shows up without a reload. */
export function useHealth() {
  return useQuery({
    queryKey: ['health'] as const,
    queryFn: () => api.getHealth(),
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
  })
}

export function usePostingDetail(postingId: string | null) {
  return useQuery({
    queryKey: ['posting', postingId] as const,
    queryFn: () => {
      if (postingId === null) throw new Error('usePostingDetail: queryFn ran without a posting id')
      return api.getPostingDetail(postingId)
    },
    enabled: postingId !== null,
  })
}

function mapCachedPages(
  data: InfiniteData<PostingsPage> | undefined,
  transform: (items: PostingOut[]) => PostingOut[],
): InfiniteData<PostingsPage> | undefined {
  if (!data) return data
  return { ...data, pages: data.pages.map((page) => ({ ...page, items: transform(page.items) })) }
}

interface FlagVariables<V> {
  postingId: string
  value: V
}

/** Optimistic update + rollback on failure, per blueprint/05-SEQUENCES.md §5. */
function useFlagMutation<V>(
  setFlag: (postingId: string, value: V) => Promise<void>,
  applyOptimistic: (items: PostingOut[], postingId: string, value: V) => PostingOut[],
) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ postingId, value }: FlagVariables<V>) => setFlag(postingId, value),
    onMutate: async ({ postingId, value }: FlagVariables<V>) => {
      await queryClient.cancelQueries({ queryKey: [POSTINGS_ROOT_KEY] })
      const previousPages = queryClient.getQueriesData<InfiniteData<PostingsPage>>({
        queryKey: [POSTINGS_ROOT_KEY],
      })
      for (const [key, data] of previousPages) {
        queryClient.setQueryData(key, mapCachedPages(data, (items) => applyOptimistic(items, postingId, value)))
      }
      const detailKey = ['posting', postingId] as const
      const previousDetail = queryClient.getQueryData<PostingDetailOut>(detailKey)
      if (previousDetail) {
        queryClient.setQueryData(detailKey, applyOptimistic([previousDetail], postingId, value)[0])
      }
      return { previousPages, previousDetail, detailKey }
    },
    onError: (_error, _variables, context) => {
      if (!context) return
      for (const [key, data] of context.previousPages) {
        queryClient.setQueryData(key, data)
      }
      if (context.previousDetail) {
        queryClient.setQueryData(context.detailKey, context.previousDetail)
      }
    },
  })
}

export function useSetFavorite() {
  return useFlagMutation<boolean>(
    (postingId, value) => api.setFavorite(postingId, value),
    (items, postingId, value) => items.map((item) => (item.posting_id === postingId ? { ...item, favorited: value } : item)),
  )
}

/** Hiding removes the row from the feed on the spot — the default filter excludes hidden postings. */
export function useSetHidden() {
  return useFlagMutation<boolean>(
    (postingId, value) => api.setHidden(postingId, value),
    (items, postingId, value) => (value ? items.filter((item) => item.posting_id !== postingId) : items),
  )
}

export type ApplicationStatus = Schemas['ApplicationStatus']

/**
 * Where an application stands. Optimistic like the favorite, and the list is refetched afterwards:
 * a status can move a posting in or out of a status-filtered view, which no local patch can know.
 */
export function useSetApplicationStatus() {
  const queryClient = useQueryClient()
  const mutation = useFlagMutation<ApplicationStatus | null>(
    (postingId, value) => api.setStatus(postingId, value),
    (items, postingId, value) =>
      items.map((item) => (item.posting_id === postingId ? { ...item, application_status: value } : item)),
  )
  return {
    ...mutation,
    mutate: (variables: { postingId: string; value: ApplicationStatus | null }) => {
      mutation.mutate(variables, {
        onSettled: () => {
          void queryClient.invalidateQueries({ queryKey: [POSTINGS_ROOT_KEY] })
        },
      })
    },
  }
}

/** Saves the note and writes it into the cached detail — the list rows do not carry it. */
export function useSetNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ postingId, note }: { postingId: string; note: string }) => api.setNote(postingId, note),
    onSuccess: (_data, { postingId, note }) => {
      const key = ['posting', postingId] as const
      const detail = queryClient.getQueryData<PostingDetailOut>(key)
      if (detail) queryClient.setQueryData(key, { ...detail, note })
    },
  })
}
