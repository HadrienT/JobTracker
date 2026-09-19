/** A stored value as a person would say it: `{amount_min: "120000", …}` → "120000–160000 GBP / year". */
export function describeValue(field: string, value: unknown): string {
  if (value === null || value === undefined) return 'none'
  if (field === 'compensation' && typeof value === 'object') {
    const pay = value as Record<string, string | null>
    const amounts = [pay.amount_min, pay.amount_max].filter((a): a is string => a !== null && a !== undefined)
    if (amounts.length === 0) return 'none'
    const range = amounts[0] === amounts[1] || amounts.length === 1 ? (amounts[0] ?? '') : amounts.join('–')
    return `${range} ${pay.currency ?? ''} / ${pay.period ?? '?'}`.replace(/\s+/g, ' ').trim()
  }
  if (field === 'locations' && Array.isArray(value)) {
    return (
      value
        .map((loc: Record<string, string | null>) => [loc.city, loc.country, loc.remote_mode !== 'unknown' ? loc.remote_mode : null].filter(Boolean).join(' '))
        .join('; ') || 'none'
    )
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  return JSON.stringify(value)
}

