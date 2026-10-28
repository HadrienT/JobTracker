import type { PostingsFilter } from '@/api/queries'
import { useCompanies, useFacets } from '@/api/queries'
import {
  DEFAULT_VISA,
  feedViewOf,
  isDefaultFilter,
  POSTED_WITHIN_OPTIONS,
  rejectionReasonLabel,
  REMOTE_MODE_OPTIONS,
  SECTOR_OPTIONS,
  SENIORITY_OPTIONS,
  STATUS_OPTIONS,
  TIER_OPTIONS,
  VIEW_TIERS,
  VISA_OPTIONS,
} from '@/features/filters/defaults'
import { FacetCheckboxGroup } from '@/features/filters/facet-checkbox-group'
import { mergeFacetOptions } from '@/features/filters/facet-options'
import { StackFilter } from '@/features/filters/stack-filter'
import { cn } from '@/shared/lib/cn'
import { useIsMobile } from '@/shared/lib/use-media-query'

interface FiltersPanelProps {
  filter: PostingsFilter
  onChange: (patch: Partial<PostingsFilter>) => void
  onReset: () => void
  /** On a phone the panel is a full-screen sheet, shown only while open; a desktop always shows it. */
  open?: boolean
  onClose?: () => void
}

/** The thirteen dimensions of blueprint/12-WEB-UI.md §4, each backed by the URL, not a store. */
export function FiltersPanel({ filter, onChange, onReset, open = false, onClose }: FiltersPanelProps) {
  const isMobile = useIsMobile()
  const facets = useFacets(filter)
  const view = feedViewOf(filter)
  const companies = useCompanies()
  const companyNameBySlug = new Map((companies.data ?? []).map((c) => [c.company_slug, c.company_name]))

  if (isMobile && !open) return null

  return (
    <aside
      aria-label="Filters"
      className={cn(
        'flex flex-col gap-1 overflow-y-auto p-4',
        isMobile ? 'fixed inset-0 z-40 bg-background pb-[max(1rem,env(safe-area-inset-bottom))]' : 'w-72 shrink-0 border-r border-border',
      )}
    >
      <div
        className={cn(
          'mb-2 flex items-center justify-between gap-4',
          isMobile && 'sticky -top-4 z-10 -mx-4 -mt-4 border-b border-border bg-background px-4 py-3',
        )}
      >
        <h2 className="text-sm font-semibold text-text-primary">Filters</h2>
        <button
          type="button"
          disabled={isDefaultFilter(filter)}
          onClick={onReset}
          className="ml-auto text-xs text-text-secondary underline decoration-dotted hover:text-text-primary disabled:pointer-events-none disabled:opacity-40"
        >
          Reset
        </button>
        {isMobile && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-tier-possible px-4 py-1.5 text-sm font-medium text-background"
          >
            Done
          </button>
        )}
      </div>

      <FacetCheckboxGroup
        title="Country"
        options={mergeFacetOptions(facets.data?.countries, filter.countries ?? [])}
        selected={filter.countries ?? []}
        onChange={(next) => {
          onChange({ countries: next })
        }}
      />

      <FacetCheckboxGroup
        title="City"
        options={mergeFacetOptions(facets.data?.cities, filter.cities ?? [])}
        selected={filter.cities ?? []}
        searchable
        searchLabel="cities"
        onChange={(next) => {
          onChange({ cities: next })
        }}
      />

      <FacetCheckboxGroup
        title="Mode"
        options={REMOTE_MODE_OPTIONS}
        selected={filter.remote_modes ?? []}
        onChange={(next) => {
          onChange({ remote_modes: next as PostingsFilter['remote_modes'] })
        }}
      />

      <FacetCheckboxGroup
        title="Company"
        options={mergeFacetOptions(facets.data?.companies, filter.companies ?? [], (slug) => companyNameBySlug.get(slug) ?? slug)}
        selected={filter.companies ?? []}
        searchable
        searchLabel="companies"
        onChange={(next) => {
          onChange({ companies: next })
        }}
      />

      <FacetCheckboxGroup
        title="Sector"
        options={SECTOR_OPTIONS.map((option) => ({ ...option, count: facets.data?.sectors[option.value] ?? 0 }))}
        selected={filter.sectors ?? []}
        onChange={(next) => {
          onChange({ sectors: next })
        }}
      />

      <FacetCheckboxGroup
        title="Seniority"
        options={SENIORITY_OPTIONS.map((option) => ({ ...option, count: facets.data?.seniorities[option.value] ?? 0 }))}
        selected={filter.seniorities ?? []}
        onChange={(next) => {
          onChange({ seniorities: next as PostingsFilter['seniorities'] })
        }}
      />

      <StackFilter filter={filter} techCounts={facets.data?.tech} onChange={onChange} />

      {/* Unchecking every box snaps back to the default pair rather than "no visa filter at
          all": a URL cannot distinguish an explicitly-empty list from an absent one, so an
          empty selection would silently reload as the default anyway — better to be honest
          about that up front than to show three empty boxes that don't survive a refresh. */}
      <FacetCheckboxGroup
        title="Visa"
        options={VISA_OPTIONS}
        selected={filter.visa ?? []}
        onChange={(next) => {
          onChange({ visa: next.length > 0 ? (next as PostingsFilter['visa']) : DEFAULT_VISA })
        }}
      />

      <FacetCheckboxGroup
        title="Tracking"
        options={STATUS_OPTIONS}
        selected={filter.statuses ?? []}
        onChange={(next) => {
          onChange({ statuses: next as PostingsFilter['statuses'] })
        }}
      />

      {view === 'rejected' ? (
        // Filtered out is one tier by definition; what splits it is why the pipeline said no.
        <FacetCheckboxGroup
          title="Filtered out because"
          options={mergeFacetOptions(facets.data?.rejection_reasons, filter.rejection_reasons ?? [], rejectionReasonLabel)}
          selected={filter.rejection_reasons ?? []}
          onChange={(next) => {
            onChange({ rejection_reasons: next })
          }}
        />
      ) : (
        <FacetCheckboxGroup
          title="Tier"
          options={TIER_OPTIONS}
          selected={filter.tiers ?? []}
          onChange={(next) => {
            onChange({ tiers: next.length > 0 ? (next as PostingsFilter['tiers']) : VIEW_TIERS[view] })
          }}
        />
      )}

      <fieldset className="flex flex-col gap-2 border-t border-border pt-4">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">Score min</legend>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={filter.min_score ?? 0}
            aria-label="Minimum score"
            onChange={(event) => {
              onChange({ min_score: Number(event.target.value) })
            }}
            className="flex-1"
          />
          <span className="w-8 text-right font-tabular text-sm text-text-primary">{filter.min_score ?? 0}</span>
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-2 border-t border-border pt-4">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">Posted since</legend>
        <div role="radiogroup" aria-label="Posted since" className="flex flex-col gap-1">
          {POSTED_WITHIN_OPTIONS.map((option) => (
            <label key={option.label} className="flex items-center gap-2 text-sm text-text-primary">
              <input
                type="radio"
                name="posted-within"
                checked={(filter.posted_within_days ?? null) === option.value}
                onChange={() => {
                  onChange({ posted_within_days: option.value })
                }}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex items-center gap-2 border-t border-border pt-4 text-sm text-text-primary">
        <input
          type="checkbox"
          checked={filter.favorites_only ?? false}
          onChange={(event) => {
            onChange({ favorites_only: event.target.checked })
          }}
        />
        Favorites only
      </label>
    </aside>
  )
}
