import type { PostingsFilter } from '@/api/queries'
import { DEFAULT_TIERS, DEFAULT_VISA, sameStringSet, STATUS_OPTIONS } from '@/features/filters/defaults'

interface Pill {
  id: string
  label: string
  onRemove: () => void
}

type ArrayDimension = 'countries' | 'cities' | 'companies' | 'sectors' | 'seniorities' | 'remote_modes' | 'tech_all' | 'tech_any' | 'statuses'

function buildPills(
  filter: PostingsFilter,
  onChange: (patch: Partial<PostingsFilter>) => void,
  companyNameBySlug: Map<string, string>,
): Pill[] {
  const pills: Pill[] = []

  function arrayDimension(key: ArrayDimension, labelFor: (value: string) => string = (value) => value) {
    const values = filter[key] ?? []
    for (const value of values) {
      pills.push({
        id: `${key}:${value}`,
        label: labelFor(value),
        onRemove: () => {
          onChange({ [key]: values.filter((v) => v !== value) })
        },
      })
    }
  }

  arrayDimension('countries')
  arrayDimension('cities')
  arrayDimension('companies', (slug) => companyNameBySlug.get(slug) ?? slug)
  arrayDimension('sectors')
  arrayDimension('seniorities')
  arrayDimension('remote_modes')
  arrayDimension('tech_all', (tech) => `${tech} (all)`)
  arrayDimension('tech_any', (tech) => `${tech} (any)`)
  arrayDimension('statuses', (status) => `Tracking: ${STATUS_OPTIONS.find((o) => o.value === status)?.label ?? status}`)

  if (!sameStringSet(filter.visa ?? [], DEFAULT_VISA)) {
    pills.push({
      id: 'visa',
      label: `Visa: ${(filter.visa ?? []).join(', ') || 'none'}`,
      onRemove: () => {
        onChange({ visa: DEFAULT_VISA })
      },
    })
  }
  if (!sameStringSet(filter.tiers ?? [], DEFAULT_TIERS)) {
    pills.push({
      id: 'tiers',
      label: `Tier: ${(filter.tiers ?? []).join(', ') || 'none'}`,
      onRemove: () => {
        onChange({ tiers: DEFAULT_TIERS })
      },
    })
  }
  if ((filter.min_score ?? 0) !== 0) {
    pills.push({
      id: 'min_score',
      label: `Score ≥ ${String(filter.min_score)}`,
      onRemove: () => {
        onChange({ min_score: 0 })
      },
    })
  }
  if (filter.posted_within_days !== null && filter.posted_within_days !== undefined) {
    pills.push({
      id: 'posted_within_days',
      label: `Posted ≤ ${String(filter.posted_within_days)}d`,
      onRemove: () => {
        onChange({ posted_within_days: null })
      },
    })
  }
  if (filter.query) {
    pills.push({
      id: 'query',
      label: `“${filter.query}”`,
      onRemove: () => {
        onChange({ query: null })
      },
    })
  }
  if (filter.favorites_only) {
    pills.push({
      id: 'favorites_only',
      label: 'Favorites only',
      onRemove: () => {
        onChange({ favorites_only: false })
      },
    })
  }

  return pills
}

interface ActiveFilterPillsProps {
  filter: PostingsFilter
  onChange: (patch: Partial<PostingsFilter>) => void
  companyNameBySlug?: Map<string, string>
}

/** A summary of every non-default filter value, each removable on its own (blueprint/12-WEB-UI.md §4). */
export function ActiveFilterPills({ filter, onChange, companyNameBySlug = new Map() }: ActiveFilterPillsProps) {
  const pills = buildPills(filter, onChange, companyNameBySlug)
  if (pills.length === 0) return null

  return (
    <ul aria-label="Active filters" className="flex flex-wrap gap-2 border-b border-border px-4 py-2">
      {pills.map((pill) => (
        <li key={pill.id}>
          <button
            type="button"
            onClick={pill.onRemove}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-elevated px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary"
          >
            {pill.label}
            <span aria-hidden="true">×</span>
            <span className="sr-only">Remove filter: {pill.label}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
