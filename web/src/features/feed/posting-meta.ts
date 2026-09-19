import type { PostingOut } from '@/mocks/contract'

const SENIORITY_LABEL: Record<PostingOut['seniority'], string> = {
  intern: 'intern',
  graduate: 'graduate',
  junior: 'junior',
  mid: 'mid',
  senior: 'senior',
  lead: 'lead',
  unknown: 'unknown',
}

export function postingMeta(posting: PostingOut): string {
  const parts = [SENIORITY_LABEL[posting.seniority]]
  if (posting.min_years !== null) parts.push(`${String(posting.min_years)}y+`)
  if (posting.tech.length > 0) parts.push(posting.tech.slice(0, 3).join(' '))
  return parts.join(' · ')
}
