import { describeValue } from '@/features/feed/describe-value'
import type { PostingDetailOut } from '@/mocks/contract'

type Correction = PostingDetailOut['llm_corrections'][number]

const FIELD_LABEL: Record<string, string> = {
  compensation: 'Compensation',
  locations: 'Locations',
  seniority: 'Seniority',
  min_years: 'Minimum years',
  visa_sponsorship: 'Visa',
  phd_required: 'PhD required',
  closes_at: 'Closing date',
}

/**
 * What the local LLM changed when it re-read this posting, each change with the exact words of the
 * posting that justify it. It is a receipt, not a control: the point is that no value here has to
 * be taken on trust — the quote is right there, and it was checked against the text.
 */
export function LlmCorrections({ corrections }: { corrections: Correction[] }) {
  if (corrections.length === 0) return null
  return (
    <section aria-label="Corrected by the local LLM" className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Corrected by the local LLM</h3>
      <ul className="flex flex-col gap-2">
        {corrections.map((correction, index) => (
          <li key={`${correction.field}-${String(index)}`} className="rounded-md border border-border p-2 text-sm">
            <p className="text-text-primary">
              <span className="font-medium">{FIELD_LABEL[correction.field] ?? correction.field}</span>{' '}
              <span className="text-text-tertiary line-through">{describeValue(correction.field, correction.before)}</span>
              {' → '}
              <span>{describeValue(correction.field, correction.after)}</span>
            </p>
            {correction.evidence && (
              <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs text-text-secondary">
                “{correction.evidence}”
              </blockquote>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
