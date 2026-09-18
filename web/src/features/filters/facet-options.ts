import type { FacetOption } from '@/features/filters/facet-checkbox-group'

/** Union of whatever `/facets` counted with whatever the user already selected — a zero-count selected value must still show up (blueprint/wp/WP11-web-filters.md §3). */
export function mergeFacetOptions(
  counts: Record<string, number> | undefined,
  selected: readonly string[],
  labelFor: (value: string) => string = (value) => value,
): FacetOption[] {
  const values = new Map<string, number>()
  for (const [value, count] of Object.entries(counts ?? {})) values.set(value, count)
  for (const value of selected) if (!values.has(value)) values.set(value, 0)
  return [...values.entries()]
    .map(([value, count]) => ({ value, label: labelFor(value), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}
