import type { PostingsFilter } from '@/api/queries'
import { FacetOptionList } from '@/features/filters/facet-checkbox-group'
import { mergeFacetOptions } from '@/features/filters/facet-options'

interface StackFilterProps {
  filter: PostingsFilter
  techCounts: Record<string, number> | undefined
  onChange: (patch: Partial<PostingsFilter>) => void
}

/** `tech_all` (every selected stack item required) vs `tech_any` (at least one) — never both at once. */
export function StackFilter({ filter, techCounts, onChange }: StackFilterProps) {
  const mode: 'all' | 'any' = (filter.tech_all?.length ?? 0) > 0 ? 'all' : 'any'
  const selected = mode === 'all' ? (filter.tech_all ?? []) : (filter.tech_any ?? [])
  const options = mergeFacetOptions(techCounts, selected)

  function setMode(nextMode: 'all' | 'any') {
    if (nextMode === mode) return
    onChange(nextMode === 'all' ? { tech_all: selected, tech_any: [] } : { tech_all: [], tech_any: selected })
  }

  return (
    <fieldset className="flex flex-col gap-2 border-t border-border pt-4">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">Stack</legend>
      <div className="flex gap-4 text-xs text-text-secondary" role="radiogroup" aria-label="Stack match mode">
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="stack-mode"
            checked={mode === 'any'}
            onChange={() => {
              setMode('any')
            }}
          />
          At least one
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="stack-mode"
            checked={mode === 'all'}
            onChange={() => {
              setMode('all')
            }}
          />
          All
        </label>
      </div>
      <FacetOptionList
        options={options}
        selected={selected}
        searchable
        searchLabel="stack"
        onChange={(next) => {
          onChange(mode === 'all' ? { tech_all: next } : { tech_any: next })
        }}
      />
    </fieldset>
  )
}
