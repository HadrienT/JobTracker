/**
 * TanStack Query hooks — the only place `features/feed` talks to the API.
 * Cache keys include both the filter and the sort key (blueprint/wp/WP10-web-feed.md
 * §2-3): changing sort is a new request, never a client-side re-sort of 15 000 rows.
 */
import {
  type InfiniteData,
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api, type CompaniesQuery, type PostingsQuery } from '@/api/client'
import type { components } from '@/api/schema.gen'

type Schemas = components['schemas']
export type PostingsFilter = Omit<PostingsQuery, 'sort' | 'cursor' | 'limit'>
export type SortKey = Schemas['SortKey']
export type Track = Schemas['Track']
type PostingsPage = Schemas['PostingsPage']
type PostingOut = Schemas['PostingOut']
type PostingDetailOut = Schemas['PostingDetailOut']

const PAGE_SIZE = 50
const POSTINGS_ROOT_KEY = 'postings' as const
const APPLICATIONS_ROOT_KEY = 'applications' as const
const CVS_ROOT_KEY = 'cvs' as const

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

/**
 * One posting, scored as `track` sees it (blueprint/wp/WP20-tracks.md) — or as the quant feed
 * does. Keyed `['posting', id, track]`: anything that changes the posting itself updates every
 * track's copy through the `['posting', id]` prefix.
 */
export function usePostingDetail(postingId: string | null, track: Track | null = null) {
  return useQuery({
    queryKey: ['posting', postingId, track] as const,
    queryFn: () => {
      if (postingId === null) throw new Error('usePostingDetail: queryFn ran without a posting id')
      return api.getPostingDetail(postingId, track)
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

/** The posting's cached detail, under every track it was opened from. */
function patchCachedDetails(queryClient: QueryClient, postingId: string, patch: Partial<PostingDetailOut>) {
  queryClient.setQueriesData<PostingDetailOut>({ queryKey: ['posting', postingId] }, (detail) =>
    detail ? { ...detail, ...patch } : detail,
  )
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
      const previousDetails = queryClient.getQueriesData<PostingDetailOut>({ queryKey: ['posting', postingId] })
      for (const [key, detail] of previousDetails) {
        if (detail) queryClient.setQueryData(key, applyOptimistic([detail], postingId, value)[0])
      }
      return { previousPages, previousDetails }
    },
    onError: (_error, _variables, context) => {
      if (!context) return
      for (const [key, data] of [...context.previousPages, ...context.previousDetails]) {
        queryClient.setQueryData(key, data)
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

export type Triage = Schemas['Triage']

/**
 * "No" / "maybe" / back to the feed. Whatever the new verdict, the posting leaves the list it
 * was read from — the feed shows what is not triaged yet, each verdict has a list of its own —
 * so the row goes on the spot and the lists are refetched for their counts and neighbours.
 */
export function useSetTriage() {
  const queryClient = useQueryClient()
  const mutation = useFlagMutation<Triage | null>(
    (postingId, value) => api.setTriage(postingId, value),
    (items, postingId, value) => items.filter((item) => item.posting_id !== postingId || item.triage === value),
  )
  return {
    ...mutation,
    mutate: (
      variables: { postingId: string; value: Triage | null },
      options?: { onSuccess?: () => void; onError?: () => void },
    ) => {
      mutation.mutate(variables, {
        onSuccess: () => {
          patchCachedDetails(queryClient, variables.postingId, { triage: variables.value })
          options?.onSuccess?.()
        },
        onError: options?.onError,
        onSettled: () => {
          void queryClient.invalidateQueries({ queryKey: [POSTINGS_ROOT_KEY] })
        },
      })
    },
  }
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
          // the status *is* an application now (WP21): the Applications tab follows
          void queryClient.invalidateQueries({ queryKey: [APPLICATIONS_ROOT_KEY] })
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
      patchCachedDetails(queryClient, postingId, { note })
    },
  })
}

// --- applications (blueprint/wp/WP21-applications.md §6) ------------------------------------

export type ApplicationOut = Schemas['ApplicationOut']
export type ApplicationDetailOut = Schemas['ApplicationDetailOut']
export type ApplicationCreate = Schemas['ApplicationCreate']
/** Every application — a few hundred rows, filtered and sorted in the tab itself. */
export function useApplications() {
  return useQuery({
    queryKey: [APPLICATIONS_ROOT_KEY],
    queryFn: () => api.listApplications(),
  })
}

export function useApplicationDetail(applicationId: string | null) {
  return useQuery({
    queryKey: [APPLICATIONS_ROOT_KEY, 'detail', applicationId],
    queryFn: () => {
      if (applicationId === null) throw new Error('useApplicationDetail: queryFn ran without an id')
      return api.getApplication(applicationId)
    },
    enabled: applicationId !== null,
  })
}

/**
 * Every application write answers with the fresh detail: it goes straight into the cache, then
 * the list is refetched — and the feed too, whose status badge mirrors a linked application.
 */
function useApplicationWrite<TVariables>(write: (variables: TVariables) => Promise<ApplicationDetailOut>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: write,
    onSuccess: (detail) => {
      queryClient.setQueryData([APPLICATIONS_ROOT_KEY, 'detail', detail.application_id], detail)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [APPLICATIONS_ROOT_KEY] })
      void queryClient.invalidateQueries({ queryKey: [POSTINGS_ROOT_KEY] })
      void queryClient.invalidateQueries({ queryKey: [CVS_ROOT_KEY] })
    },
  })
}

export function useCreateApplication() {
  return useApplicationWrite((body: ApplicationCreate) => api.createApplication(body))
}

export function useRecordApplicationStatus() {
  return useApplicationWrite(
    ({ applicationId, body }: { applicationId: string; body: Schemas['ApplicationStatusRequest'] }) =>
      api.recordApplicationStatus(applicationId, body),
  )
}

export function useEditApplication() {
  return useApplicationWrite(
    ({ applicationId, body }: { applicationId: string; body: Schemas['ApplicationEditRequest'] }) =>
      api.editApplication(applicationId, body),
  )
}

export function useArchiveOffer() {
  return useApplicationWrite(({ applicationId, body }: { applicationId: string; body: Schemas['OfferTextRequest'] }) =>
    api.archiveOffer(applicationId, body),
  )
}

export function useUploadApplicationFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ applicationId, file }: { applicationId: string; file: File }) =>
      api.uploadApplicationFile(applicationId, file),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [APPLICATIONS_ROOT_KEY] })
      void queryClient.invalidateQueries({ queryKey: [CVS_ROOT_KEY] })
    },
  })
}

// --- CVs (blueprint/wp/WP22-cvs.md §4) -------------------------------------------------------

export type CvOut = Schemas['CvOut']

/** Every CV, newest first — the versions are the pinned ones. */
export function useCvs() {
  return useQuery({
    queryKey: [CVS_ROOT_KEY],
    queryFn: () => api.listCvs(),
  })
}

/** Also what confirms a CV that was only assumed: choosing it again is the user's answer. */
export function useSetApplicationCv() {
  return useApplicationWrite(({ applicationId, cvId }: { applicationId: string; cvId: string | null }) =>
    api.setApplicationCv(applicationId, cvId),
  )
}

export function useUploadCv() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadCv(file),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [CVS_ROOT_KEY] })
    },
  })
}

export function useEditCv() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ cvId, body }: { cvId: string; body: Schemas['CvEditRequest'] }) => api.editCv(cvId, body),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [CVS_ROOT_KEY] })
    },
  })
}

export function useDeleteApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (applicationId: string) => api.deleteApplication(applicationId),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [APPLICATIONS_ROOT_KEY] })
      void queryClient.invalidateQueries({ queryKey: [POSTINGS_ROOT_KEY] })
    },
  })
}
