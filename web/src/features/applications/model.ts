import type { ApplicationOut, ApplicationStatus, CvOut } from '@/api/queries'

/**
 * The Applications tab's views, filters, sort and numbers (blueprint/wp/WP21-applications.md §6)
 * — pure functions over the list `/applications` returns. `open` and `abandoned` come from the
 * API, derived on every read (five months without news, §2.3): the tab never re-derives them.
 */

export type ApplicationView = 'open' | 'all' | 'interviews' | 'rejected' | 'abandoned' | 'offers'

export const VIEWS: { value: ApplicationView; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'all', label: 'All' },
  { value: 'interviews', label: 'Interviews' },
  { value: 'offers', label: 'Offers' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'abandoned', label: 'No news 5+ months' },
]

export type SortColumn = 'applied' | 'company' | 'status' | 'answer'

export interface ApplicationFilter {
  view: ApplicationView
  query: string
  year: number | null
  /** ISO code; an application in several countries matches each of them. */
  country: string | null
  /** Only the applications whose CV is not recorded: what is left to fill in. */
  noCv: boolean
}

const DAY_MS = 24 * 60 * 60 * 1000

function day(text: string): number {
  return new Date(`${text}T00:00:00Z`).getTime()
}

export function daysBetween(from: string, to: string): number {
  return Math.round((day(to) - day(from)) / DAY_MS)
}

/** How long they took to answer — or how long it has been, still waiting. */
export function answerDelay(application: ApplicationOut, today: string): { days: number; waiting: boolean } | null {
  if (application.applied_on === null) return null
  if (application.closed_on !== null) {
    return {
      days: daysBetween(application.applied_on, application.closed_on),
      waiting: false,
    }
  }
  if (application.status === 'applied' || application.status === 'interview') {
    return { days: daysBetween(application.applied_on, today), waiting: true }
  }
  return null
}

function inView(application: ApplicationOut, view: ApplicationView): boolean {
  switch (view) {
    case 'open':
      return application.open
    case 'all':
      return true
    case 'interviews':
      return application.reached_interview
    case 'offers':
      return application.status === 'offer'
    case 'rejected':
      return application.status === 'rejected'
    case 'abandoned':
      return application.abandoned
  }
}

function fold(text: string): string {
  return text.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

export function filterApplications(applications: ApplicationOut[], filter: ApplicationFilter): ApplicationOut[] {
  const needle = fold(filter.query.trim())
  return applications.filter((application) => {
    if (!inView(application, filter.view)) return false
    if (filter.year !== null && application.applied_on?.slice(0, 4) !== String(filter.year)) return false
    if (filter.country !== null && !application.countries.includes(filter.country)) return false
    if (filter.noCv && application.cv_id !== null) return false
    if (needle === '') return true
    const haystack = fold([application.company, application.title ?? '', application.location ?? ''].join(' '))
    return haystack.includes(needle)
  })
}

const STATUS_ORDER: Record<ApplicationStatus, number> = {
  offer: 0,
  interview: 1,
  applied: 2,
  rejected: 3,
  withdrawn: 4,
}

export function sortApplications(
  applications: ApplicationOut[],
  column: SortColumn,
  descending: boolean,
  today: string,
): ApplicationOut[] {
  const key = (a: ApplicationOut): number | string => {
    switch (column) {
      case 'applied':
        return a.applied_on ?? ''
      case 'company':
        return fold(a.company)
      case 'status':
        return STATUS_ORDER[a.status]
      case 'answer':
        return answerDelay(a, today)?.days ?? -1
    }
  }
  const sorted = [...applications].sort((left, right) => {
    const a = key(left)
    const b = key(right)
    if (a < b) return -1
    if (a > b) return 1
    return left.application_id < right.application_id ? -1 : 1
  })
  return descending ? sorted.reverse() : sorted
}

/** How many applications name each country — most first: the legend, which doubles as a filter. */
export function countryCounts(applications: ApplicationOut[]): { code: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const application of applications) {
    for (const code of application.countries) counts.set(code, (counts.get(code) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([code, count]) => ({ code, count }))
    .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code))
}

export function yearsOf(applications: ApplicationOut[]): number[] {
  const years = new Set<number>()
  for (const application of applications) {
    if (application.applied_on !== null) years.add(Number(application.applied_on.slice(0, 4)))
  }
  return [...years].sort((a, b) => b - a)
}

export interface ApplicationStats {
  total: number
  open: number
  abandoned: number
  interviews: number
  offers: number
  rejected: number
  /** Share of applications that got any answer: an interview, an offer or a rejection. */
  responseRate: number | null
  /** Days from applying to a rejection, median. */
  medianDaysToRejection: number | null
}

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  const upper = sorted[middle] ?? 0
  return sorted.length % 2 === 1 ? upper : ((sorted[middle - 1] ?? upper) + upper) / 2
}

export function applicationStats(applications: ApplicationOut[]): ApplicationStats {
  const answered = applications.filter(
    (a) => a.reached_interview || a.status === 'offer' || a.status === 'rejected',
  ).length
  const delays = applications.flatMap((a) =>
    a.status === 'rejected' && a.applied_on !== null && a.closed_on !== null
      ? [daysBetween(a.applied_on, a.closed_on)]
      : [],
  )
  return {
    total: applications.length,
    open: applications.filter((a) => a.open).length,
    abandoned: applications.filter((a) => a.abandoned).length,
    interviews: applications.filter((a) => a.reached_interview).length,
    offers: applications.filter((a) => a.status === 'offer').length,
    rejected: applications.filter((a) => a.status === 'rejected').length,
    responseRate: applications.length === 0 ? null : answered / applications.length,
    medianDaysToRejection: median(delays),
  }
}

export interface CvStats {
  cv: CvOut
  sent: number
  /** Links only assumed, not confirmed: the rate below is as good as they are. */
  inferred: number
  interviews: number
  responseRate: number | null
}

/**
 * The versions in use, newest first, with what became of the applications sent with each. The
 * same definition of an answer as `applicationStats`; the offers aimed at differ from one version
 * to the next, so this tells a trend, not a cause.
 */
export function cvStats(cvs: CvOut[], applications: ApplicationOut[]): CvStats[] {
  return cvs.flatMap((cv) => {
    const sent = applications.filter((a) => a.cv_id === cv.cv_id)
    if (!cv.pinned || sent.length === 0) return []
    return [
      {
        cv,
        sent: sent.length,
        inferred: sent.filter((a) => a.cv_source === 'inferred').length,
        interviews: sent.filter((a) => a.reached_interview).length,
        responseRate: applicationStats(sent).responseRate,
      },
    ]
  })
}

/** Today as `YYYY-MM-DD`, in the viewer's own calendar. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${String(now.getFullYear())}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
