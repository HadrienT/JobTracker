import type { SalaryPeriod } from '@/mocks/contract'
import { formatMoneyRange } from '@/shared/lib/money'
import { Empty } from '@/shared/ui/empty'

const PERIOD_SUFFIX: Record<SalaryPeriod, string> = {
  year: '/year',
  month: '/mo',
  day: '/day',
  hour: '/hr',
}

interface MoneyProps {
  amountMin: string | null
  amountMax: string | null
  currency: string | null
  period: SalaryPeriod | null
}

/** A range in its origin currency — never converted. Absent renders `<Empty>`, never `0`. */
export function Money({ amountMin, amountMax, currency, period }: MoneyProps) {
  const formatted = formatMoneyRange(amountMin, amountMax, currency)
  if (formatted === null) return <Empty />
  return (
    <span className="font-tabular text-text-primary">
      {formatted}
      {period !== null && <span className="text-text-tertiary"> {PERIOD_SUFFIX[period]}</span>}
    </span>
  )
}
