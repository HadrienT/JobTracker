import { useId, useState } from 'react'
import { cn } from '@/shared/lib/cn'

export interface FacetOption {
  value: string
  label: string
  /** `undefined` when `/facets` doesn't count this dimension (visa, tiers, remote mode). */
  count?: number
}

interface FacetOptionListProps {
  options: FacetOption[]
  selected: readonly string[]
  onChange: (next: string[]) => void
  searchable?: boolean
  searchLabel?: string
}

/**
 * A zero-count option is rendered greyed out, never dropped — hiding a
 * checkbox is a checkbox nobody can ever uncheck again (blueprint/wp/WP11-web-filters.md
 * §3). `options` is expected to already include every currently-selected
 * value, even one `/facets` didn't return under the current filter.
 */
export function FacetOptionList({ options, selected, onChange, searchable = false, searchLabel = 'options' }: FacetOptionListProps) {
  const [search, setSearch] = useState('')
  const groupId = useId()
  const selectedSet = new Set(selected)
  const visible = searchable
    ? options.filter((option) => option.label.toLowerCase().includes(search.toLowerCase()))
    : options

  function toggle(value: string) {
    onChange(selectedSet.has(value) ? selected.filter((v) => v !== value) : [...selected, value])
  }

  return (
    <div className="flex flex-col gap-2">
      {searchable && (
        <input
          type="search"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
          }}
          placeholder={`Search ${searchLabel}…`}
          aria-label={`Search ${searchLabel}`}
          className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary"
        />
      )}
      <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
        {visible.length === 0 && <p className="text-xs text-text-tertiary">No match.</p>}
        {visible.map((option) => {
          const zero = option.count === 0
          const inputId = `${groupId}-${option.value}`
          return (
            <label
              key={option.value}
              htmlFor={inputId}
              className={cn('flex cursor-pointer items-center justify-between gap-2 text-sm', zero && 'opacity-50')}
            >
              <span className="flex items-center gap-2">
                <input
                  id={inputId}
                  type="checkbox"
                  checked={selectedSet.has(option.value)}
                  onChange={() => {
                    toggle(option.value)
                  }}
                />
                <span className="text-text-primary">{option.label}</span>
              </span>
              {option.count !== undefined && <span className="font-tabular text-xs text-text-tertiary">{option.count}</span>}
            </label>
          )
        })}
      </div>
    </div>
  )
}

interface FacetCheckboxGroupProps extends FacetOptionListProps {
  title: string
}

/** `FacetOptionList` wrapped in its own `<fieldset>`/`<legend>` — the shape most panel rows want. */
export function FacetCheckboxGroup({ title, ...listProps }: FacetCheckboxGroupProps) {
  return (
    <fieldset className="flex flex-col gap-2 border-t border-border pt-4">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">{title}</legend>
      <FacetOptionList {...listProps} />
    </fieldset>
  )
}
