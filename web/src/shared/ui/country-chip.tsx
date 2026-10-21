import { cn } from '@/shared/lib/cn'
import { COUNTRY_TONES, countryName, OTHER_TONE } from '@/shared/lib/countries'

interface CountryChipProps {
  code: string
  className?: string
}

/** A country's code in its spreadsheet colour (`shared/lib/countries.ts`); its name on hover. */
export function CountryChip({ code, className }: CountryChipProps) {
  return (
    <span
      title={countryName(code)}
      className={cn(
        'inline-flex shrink-0 items-center rounded border px-1 py-px font-tabular text-[10px] font-semibold leading-none',
        (COUNTRY_TONES[code] ?? OTHER_TONE).chip,
        className,
      )}
    >
      {code === 'GB' ? 'UK' : code}
    </span>
  )
}
