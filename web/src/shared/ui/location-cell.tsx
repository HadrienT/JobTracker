import type { Location } from '@/mocks/contract'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/ui/tooltip'

const MODE_LABEL: Record<Location['remote_mode'], string> = {
  onsite: 'onsite',
  hybrid: 'hybrid',
  remote: 'remote',
  unknown: '',
}

function primaryLabel(location: Location): string {
  if (location.city !== null && location.country !== null) {
    return `${location.city} ${location.country}`
  }
  // A country without a city: the raw string is often the whole multi-site list.
  if (location.country !== null) return location.country
  return location.raw ?? '?? ??'
}

interface LocationCellProps {
  locations: Location[]
}

/**
 * `City COUNTRY` + mode, `+2` for multi-site, the raw source string on hover. The label
 * truncates: a raw fallback can run to a thousand characters and must stay in its column.
 */
export function LocationCell({ locations }: LocationCellProps) {
  const [primary, ...rest] = locations
  if (!primary) return null
  const mode = MODE_LABEL[primary.remote_mode]
  // Sites split from one source string all carry that same string.
  const rawList = [...new Set(locations.map((l) => l.raw))]
    .filter((raw): raw is string => raw !== null)
    .join(' · ')

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 text-text-primary">
          <span className="truncate">{primaryLabel(primary)}</span>
          {mode !== '' && <span className="shrink-0 text-text-tertiary">{mode}</span>}
          {rest.length > 0 && <span className="shrink-0 text-text-tertiary">+{rest.length}</span>}
        </span>
      </TooltipTrigger>
      {rawList !== '' && <TooltipContent className="line-clamp-[12]">{rawList}</TooltipContent>}
    </Tooltip>
  )
}
