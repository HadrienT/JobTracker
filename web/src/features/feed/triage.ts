import type { Triage } from '@/api/queries'
import type { FeedView } from '@/features/filters/defaults'

/** A posting's place: the feed (not triaged yet) or one of the two verdict lists. */
export type TriageView = Triage | null

export const FEED_VIEWS: { value: FeedView; label: string }[] = [
  { value: 'inbox', label: 'Inbox' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'no', label: 'No' },
  { value: 'applied', label: 'Applied' },
  { value: 'rejected', label: 'Filtered out' },
]

export const TRIAGE_VIEWS: { value: TriageView; label: string }[] = [
  { value: null, label: 'Inbox' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'no', label: 'No' },
]

/** What a row offers: every place but the one it is in. Shortcut keys match `use-keyboard-shortcuts`. */
export const TRIAGE_ACTIONS: { value: TriageView; label: string; glyph: string; done: string }[] = [
  { value: 'maybe', label: 'Maybe (m)', glyph: '?', done: 'Moved to Maybe.' },
  { value: 'no', label: 'No (n)', glyph: '✕', done: 'Moved to No.' },
  { value: null, label: 'Back to inbox (u)', glyph: '↩', done: 'Back in the inbox.' },
]
