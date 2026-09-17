import { formatDeadline } from '@/shared/lib/dates'
import { Empty } from '@/shared/ui/empty'

interface DeadlineProps {
  closesAt: string | null
  now?: Date
}

/** `closes in 6d`, red — absent (or already elapsed) renders `<Empty>`. */
export function Deadline({ closesAt, now }: DeadlineProps) {
  if (closesAt === null) return <Empty />
  const label = formatDeadline(closesAt, now)
  if (label === null) return <Empty />
  return <span className="font-tabular text-danger">{label.text}</span>
}
