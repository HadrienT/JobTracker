import { useEffect, useMemo, useState } from 'react'
import { type ApplicationOut, type CvOut, useApplications, useCvs } from '@/api/queries'
import { ApplicationDetailPanel } from '@/features/applications/application-detail-panel'
import {
  type ApplicationFilter,
  type ApplicationView,
  answerDelay,
  applicationStats,
  countryCounts,
  cvStats,
  filterApplications,
  type SortColumn,
  sortApplications,
  todayIso,
  VIEWS,
  yearsOf,
} from '@/features/applications/model'
import { NewApplicationDialog } from '@/features/applications/new-application-dialog'
import { StatusBadge } from '@/features/feed/status-badge'
import { usePostingRoute } from '@/features/feed/routing'
import { cn } from '@/shared/lib/cn'
import { countryName, countryTint } from '@/shared/lib/countries'
import { CountryChip } from '@/shared/ui/country-chip'

const VIEW_VALUES = new Set<string>(VIEWS.map((view) => view.value))

/** The filter rides in the query string, like the feed's: a reload or a shared link keeps it. */
function readFilter(): ApplicationFilter {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view') ?? 'open'
  const year = Number(params.get('year'))
  return {
    view: (VIEW_VALUES.has(view) ? view : 'open') as ApplicationView,
    query: params.get('q') ?? '',
    year: Number.isInteger(year) && year > 2000 ? year : null,
    country: /^[A-Z]{2}$/.test(params.get('country') ?? '') ? params.get('country') : null,
    noCv: params.get('cv') === 'none',
  }
}

function writeFilter(filter: ApplicationFilter) {
  const params = new URLSearchParams()
  if (filter.view !== 'open') params.set('view', filter.view)
  if (filter.query !== '') params.set('q', filter.query)
  if (filter.year !== null) params.set('year', String(filter.year))
  if (filter.country !== null) params.set('country', filter.country)
  if (filter.noCv) params.set('cv', 'none')
  const search = params.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${search === '' ? '' : `?${search}`}`)
}

function percent(value: number | null): string {
  return value === null ? '—' : `${String(Math.round(value * 100))}%`
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col rounded-md border border-border px-2 py-1.5 md:min-w-28 md:px-3 md:py-2" title={hint}>
      <span className="text-xs leading-tight text-text-secondary">{label}</span>
      <span className="font-tabular text-lg font-semibold text-text-primary">{value}</span>
    </div>
  )
}

/** `wide`: a phone drops the column — the company moves under the job title instead. */
const COLUMNS: { column: SortColumn | null; label: string; wide?: boolean }[] = [
  { column: 'applied', label: 'Applied' },
  { column: 'company', label: 'Company', wide: true },
  { column: null, label: 'Job' },
  { column: null, label: 'Location', wide: true },
  { column: 'status', label: 'Status' },
  { column: 'answer', label: 'Answer', wide: true },
  { column: null, label: 'CV', wide: true },
]

const WIDE_ONLY = 'hidden md:table-cell'

/**
 * Every application, collected posting or not (blueprint/wp/WP21-applications.md §6): the
 * imported history, what the feed recorded, what was typed in by hand. `/applications/p/{id}`
 * opens one on top, as the feed's `/p/{id}` does.
 */
export function ApplicationsScreen() {
  const applications = useApplications()
  const cvs = useCvs()
  const route = usePostingRoute('/applications')
  const [filter, setFilter] = useState<ApplicationFilter>(readFilter)
  const [sort, setSort] = useState<{ column: SortColumn; descending: boolean }>({
    column: 'applied',
    descending: true,
  })
  const [creating, setCreating] = useState(false)
  const today = todayIso()

  useEffect(() => {
    writeFilter(filter)
  }, [filter])

  const all = useMemo(() => applications.data ?? [], [applications.data])
  const stats = useMemo(() => applicationStats(all), [all])
  const shown = useMemo(
    () => sortApplications(filterApplications(all, filter), sort.column, sort.descending, today),
    [all, filter, sort, today],
  )
  const years = useMemo(() => yearsOf(all), [all])
  const allCvs = useMemo(() => cvs.data ?? [], [cvs.data])
  const cvLabels = useMemo(() => new Map(allCvs.map((cv) => [cv.cv_id, cv.label])), [allCvs])
  const versions = useMemo(() => cvStats(allCvs, all), [allCvs, all])
  const withoutCv = useMemo(() => all.filter((application) => application.cv_id === null).length, [all])
  // The legend counts what the other filters leave, so a click never lands on an empty list.
  const countries = useMemo(() => countryCounts(filterApplications(all, { ...filter, country: null })), [all, filter])

  function sortBy(column: SortColumn) {
    setSort((current) =>
      current.column === column
        ? { column, descending: !current.descending }
        : { column, descending: column !== 'company' },
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-3 md:p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">Applications</h1>
        <button
          type="button"
          onClick={() => {
            setCreating(true)
          }}
          className="ml-auto rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-surface-elevated"
        >
          New application
        </button>
      </div>

      {applications.isPending && <p className="text-sm text-text-tertiary">Loading…</p>}
      {applications.isError && <p className="text-sm text-danger">Couldn&apos;t load the applications.</p>}

      {applications.data && (
        <>
          <section aria-label="Summary" className="mb-4 grid grid-cols-3 gap-2 md:flex md:flex-wrap">
            <Stat label="Applications" value={String(stats.total)} />
            <Stat
              label="Open"
              value={String(stats.open)}
              hint="Applied or interviewing, with news in the last five months"
            />
            <Stat label="Interviews" value={String(stats.interviews)} />
            <Stat label="Offers" value={String(stats.offers)} />
            <Stat label="Rejected" value={String(stats.rejected)} />
            <Stat
              label="No news 5+ months"
              value={String(stats.abandoned)}
              hint="Still marked applied or interview, nothing heard for five months: counted as abandoned"
            />
            <Stat
              label="Response rate"
              value={percent(stats.responseRate)}
              hint="Applications that got any answer: an interview, an offer or a rejection"
            />
            <Stat
              label="Median time to a no"
              value={stats.medianDaysToRejection === null ? '—' : `${String(Math.round(stats.medianDaysToRejection))}d`}
            />
          </section>

          {versions.length > 0 && <CvVersions versions={versions} />}

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div role="group" aria-label="View" className="flex flex-wrap gap-1">
              {VIEWS.map((view) => (
                <button
                  key={view.value}
                  type="button"
                  aria-pressed={filter.view === view.value}
                  onClick={() => {
                    setFilter((current) => ({ ...current, view: view.value }))
                  }}
                  className={cn(
                    'rounded-md border px-2 py-1 text-sm',
                    filter.view === view.value
                      ? 'border-text-secondary bg-surface-elevated text-text-primary'
                      : 'border-border text-text-secondary hover:text-text-primary',
                  )}
                >
                  {view.label}
                </button>
              ))}
            </div>
            <input
              type="search"
              aria-label="Search applications"
              placeholder="Company, job, place…"
              value={filter.query}
              onChange={(event) => {
                setFilter((current) => ({
                  ...current,
                  query: event.target.value,
                }))
              }}
              className="min-w-48 flex-1 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary"
            />
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              Year
              <select
                value={filter.year ?? ''}
                onChange={(event) => {
                  const value = event.target.value
                  setFilter((current) => ({
                    ...current,
                    year: value === '' ? null : Number(value),
                  }))
                }}
                className="rounded-md border border-border bg-surface px-2 py-1 text-text-primary"
              >
                <option value="">All</option>
                {years.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              aria-pressed={filter.noCv}
              onClick={() => {
                setFilter((current) => ({ ...current, noCv: !current.noCv }))
              }}
              className={cn(
                'rounded-md border px-2 py-1 text-sm',
                filter.noCv
                  ? 'border-text-secondary bg-surface-elevated text-text-primary'
                  : 'border-border text-text-secondary hover:text-text-primary',
              )}
            >
              No CV ({withoutCv})
            </button>
            <span className="text-xs text-text-tertiary" aria-live="polite">
              {shown.length} shown
            </span>
          </div>

          {countries.length > 0 && (
            <div role="group" aria-label="Countries" className="mb-3 flex flex-wrap items-center gap-1.5">
              {countries.map(({ code, count }) => (
                <button
                  key={code}
                  type="button"
                  aria-pressed={filter.country === code}
                  aria-label={`${countryName(code)}: ${String(count)}`}
                  onClick={() => {
                    setFilter((current) => ({ ...current, country: current.country === code ? null : code }))
                  }}
                  className={cn(
                    'flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs',
                    filter.country === code
                      ? 'border-text-secondary bg-surface-elevated text-text-primary'
                      : 'border-transparent text-text-secondary hover:border-border',
                  )}
                >
                  <CountryChip code={code} />
                  <span className="font-tabular">{count}</span>
                </button>
              ))}
              {filter.country !== null && (
                <button
                  type="button"
                  onClick={() => {
                    setFilter((current) => ({ ...current, country: null }))
                  }}
                  className="text-xs text-text-tertiary hover:text-text-primary"
                >
                  All countries
                </button>
              )}
            </div>
          )}

          {shown.length === 0 ? (
            <p className="text-sm text-text-tertiary">Nothing here.</p>
          ) : (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-secondary">
                  {COLUMNS.map(({ column, label, wide }) => (
                    <th
                      key={label}
                      className={cn('py-2 pr-4', wide && WIDE_ONLY)}
                      aria-sort={
                        column !== null && sort.column === column
                          ? sort.descending
                            ? 'descending'
                            : 'ascending'
                          : undefined
                      }
                    >
                      {column === null ? (
                        label
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            sortBy(column)
                          }}
                          className="uppercase hover:text-text-primary"
                        >
                          {label}
                          {sort.column === column && (sort.descending ? ' ↓' : ' ↑')}
                        </button>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((application) => (
                  <ApplicationRow
                    key={application.application_id}
                    application={application}
                    today={today}
                    cvLabel={application.cv_id === null ? null : (cvLabels.get(application.cv_id) ?? null)}
                    onOpen={route.openPosting}
                  />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {route.postingId !== null && (
        <ApplicationDetailPanel applicationId={route.postingId} onClose={route.closePosting} />
      )}
      {creating && (
        <NewApplicationDialog
          onClose={() => {
            setCreating(false)
          }}
          onCreated={(applicationId) => {
            setCreating(false)
            route.openPosting(applicationId)
          }}
        />
      )}
    </div>
  )
}

function CvVersions({ versions }: { versions: ReturnType<typeof cvStats> }) {
  return (
    <details className="mb-4 rounded-md border border-border px-3 py-2 text-sm">
      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-text-secondary">
        CV versions
      </summary>
      <table className="mt-2 w-full border-collapse">
        <thead>
          <tr className="text-left text-xs text-text-secondary">
            <th className="py-1 pr-4 font-normal">Version</th>
            <th className="py-1 pr-4 font-normal">Sent</th>
            <th className="py-1 pr-4 font-normal">Interviews</th>
            <th className="py-1 font-normal">Response rate</th>
          </tr>
        </thead>
        <tbody className="font-tabular text-text-primary">
          {versions.map(({ cv, sent, inferred, interviews, responseRate }) => (
            <tr key={cv.cv_id} className="border-t border-border/60">
              <td className="py-1 pr-4">{cv.label}</td>
              <td className="py-1 pr-4">
                {sent}
                {inferred > 0 && <span className="text-text-tertiary"> ({inferred} inferred)</span>}
              </td>
              <td className="py-1 pr-4">{interviews}</td>
              <td className="py-1">{percent(responseRate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-text-tertiary">
        A trend, not a cause: each version went to different offers.
      </p>
    </details>
  )
}

function ApplicationRow({
  application,
  today,
  cvLabel,
  onOpen,
}: {
  application: ApplicationOut
  today: string
  cvLabel: CvOut['label'] | null
  onOpen: (applicationId: string) => void
}) {
  const delay = answerDelay(application, today)
  return (
    <tr
      data-testid="application-row"
      className={cn(
        'cursor-pointer border-b border-border/60 hover:bg-surface-elevated',
        application.abandoned && 'opacity-60',
      )}
      onClick={() => {
        onOpen(application.application_id)
      }}
    >
      <td className="whitespace-nowrap py-1.5 pr-4 font-tabular text-text-secondary">
        {application.applied_on ?? '?'}
        {application.applied_on_estimated && (
          <span title="Estimated from the date of the screenshots" className="text-text-tertiary">
            ~
          </span>
        )}
      </td>
      <td className={cn('py-1.5 pr-4 text-text-primary', WIDE_ONLY)}>{application.company}</td>
      <td className="py-1.5 pr-4">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onOpen(application.application_id)
          }}
          className="text-left text-text-primary hover:underline"
        >
          {application.title ?? <span className="text-text-tertiary">(no title)</span>}
        </button>
        <span className="block text-xs text-text-secondary md:hidden">
          {[application.company, application.location].filter(Boolean).join(' · ')}
        </span>
      </td>
      <td className={cn('py-1.5 pr-4 text-text-secondary', WIDE_ONLY, countryTint(application.countries[0]))}>
        <span className="flex flex-wrap items-center gap-1.5">
          {application.countries.map((code) => (
            <CountryChip key={code} code={code} />
          ))}
          {application.location ?? (application.countries.length === 0 ? '—' : '')}
        </span>
      </td>
      <td className="py-1.5 pr-4">
        <span className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={application.status} />
          {application.abandoned && <span className="text-xs text-text-tertiary">no news 5+ mo</span>}
          {application.note.trim() !== '' && (
            // The status may not be the whole story (an unattributed rejection, a referral…).
            <span
              title={application.note}
              aria-label={`Note: ${application.note}`}
              className="rounded border border-warning px-1 text-xs text-warning"
            >
              note
            </span>
          )}
          {application.reached_interview && application.status === 'rejected' && (
            <span className="text-xs text-tier-stretch" title={application.reason}>
              after interview
            </span>
          )}
        </span>
      </td>
      <td className={cn('whitespace-nowrap py-1.5 pr-4 font-tabular text-text-secondary', WIDE_ONLY)}>
        {delay === null ? '—' : delay.waiting ? `waiting ${String(delay.days)}d` : `${String(delay.days)}d`}
      </td>
      <td className={cn('max-w-44 truncate py-1.5 pr-4 text-text-secondary', WIDE_ONLY)} title={cvLabel ?? undefined}>
        {cvLabel ?? <span className="text-text-tertiary">—</span>}
        {application.cv_source === 'inferred' && (
          <span title="Assumed, not confirmed" className="text-text-tertiary">
            {' '}
            ?
          </span>
        )}
      </td>
    </tr>
  )
}
