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
  return location.raw ?? '?? ??'
}

interface LocationCellProps {
  locations: Location[]
}

/** `City COUNTRY` + mode, `+2` for multi-site, the raw source string on hover. */
export function LocationCell({ locations }: LocationCellProps) {
  const [primary, ...rest] = locations
  if (!primary) return null
  const mode = MODE_LABEL[primary.remote_mode]
  const rawList = locations
    .map((l) => l.raw)
    .filter((raw): raw is string => raw !== null)
    .join(' · ')

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center gap-1.5 text-text-primary">
          <span>{primaryLabel(primary)}</span>
          {mode !== '' && <span className="text-text-tertiary">{mode}</span>}
          {rest.length > 0 && <span className="text-text-tertiary">+{rest.length}</span>}
        </span>
      </TooltipTrigger>
      {rawList !== '' && <TooltipContent>{rawList}</TooltipContent>}
    </Tooltip>
  )
}
