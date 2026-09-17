/**
 * The posting-age formula of blueprint/09-CONVENTIONS.md §3 ("La règle des dates
 * de publication"): sources lie about `posted_at`, so `first_seen_at` — written by
 * us — is the fallback whenever `posted_at` is missing or absurdly in the future.
 */
export function displayedPostingDate(postedAt: string | null, firstSeenAt: string): Date {
  if (postedAt !== null) {
    const posted = new Date(postedAt)
    const firstSeen = new Date(firstSeenAt)
    if (posted.getTime() < firstSeen.getTime()) return posted
  }
  return new Date(firstSeenAt)
}

export interface AgeLabel {
  text: string
  stale: boolean
}

/** `3d`, `2w`, `47d` — orange past half of `staleAfterDays`. */
export function formatAge(date: Date, staleAfterDays: number, now: Date = new Date()): AgeLabel {
  const ms = Math.max(0, now.getTime() - date.getTime())
  const days = Math.floor(ms / (1000 * 60 * 60 * 24))
  const text = days >= 14 ? `${String(Math.floor(days / 7))}w` : `${String(days)}d`
  return { text, stale: days >= staleAfterDays / 2 }
}

export interface DeadlineLabel {
  text: string
  daysLeft: number
}

/** `closes in 6d` — `null` when the closing date is past or already elapsed today. */
export function formatDeadline(closesAt: string, now: Date = new Date()): DeadlineLabel | null {
  const close = new Date(closesAt)
  const msLeft = close.getTime() - now.getTime()
  const daysLeft = Math.ceil(msLeft / (1000 * 60 * 60 * 24))
  if (daysLeft < 0) return null
  return { text: `closes in ${String(daysLeft)}d`, daysLeft }
}
