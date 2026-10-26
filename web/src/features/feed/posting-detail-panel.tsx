import { useRef } from 'react'
import { api } from '@/api/client'
import type { components } from '@/api/schema.gen'
import { type Track, usePostingDetail, useSetTriage } from '@/api/queries'
import { TRIAGE_VIEWS } from '@/features/feed/triage'
import { rejectionReasonLabel } from '@/features/filters/defaults'
import { cn } from '@/shared/lib/cn'
import { useModal } from '@/shared/lib/use-modal'
import { LlmCorrections } from '@/features/feed/llm-corrections'
import { TrackingSection } from '@/features/feed/tracking-section'
import { Age } from '@/shared/ui/age'
import { Deadline } from '@/shared/ui/deadline'
import { LocationCell } from '@/shared/ui/location-cell'
import { Money } from '@/shared/ui/money'
import { Score } from '@/shared/ui/score'
import { VisaBadge } from '@/shared/ui/visa-badge'

interface PostingDetailPanelProps {
  postingId: string
  onClose: () => void
  /** The track the posting was opened from: its score and reasons are that track's. */
  track?: Track | null
}

/**
 * `/p/{id}` rendered as a real modal on top of the feed (blueprint/wp/WP10-web-feed.md
 * §5): `aria-modal`, a focus trap, focus restitution on close, `Échap` to close.
 */
export function PostingDetailPanel({ postingId, onClose, track = null }: PostingDetailPanelProps) {
  const { data: posting, isPending, isError } = usePostingDetail(postingId, track)
  const setTriage = useSetTriage()
  const panelRef = useRef<HTMLDivElement>(null)
  useModal(panelRef)

  const visaReason = posting?.reasons.find((reason) => reason.code.toLowerCase().includes('sponsor'))

  return (
    // A click on the dimmed area (the overlay itself, never the panel or its children) closes.
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/50"
      data-testid="posting-detail-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="posting-detail-title"
        tabIndex={-1}
        className="flex h-full w-full max-w-xl flex-col gap-4 overflow-y-auto border-l border-border bg-surface p-6 outline-none"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="posting-detail-title" className="text-lg font-semibold text-text-primary">
            {posting?.title ?? 'Posting detail'}
          </h2>
          <button
            type="button"
            aria-label="Close"
            className="rounded-md border border-border px-2 py-1 text-text-secondary hover:bg-surface-elevated"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {isPending && <p className="text-sm text-text-tertiary">Loading…</p>}
        {isError && <p className="text-sm text-danger">Couldn&apos;t load this posting.</p>}

        {posting && (
          <>
            <p className="text-sm text-text-secondary">
              {posting.company_name} · {posting.sector}
            </p>

            {posting.rejection_reason !== null && (
              <p className="text-sm text-tier-rejected">
                Filtered out by the pipeline: {rejectionReasonLabel(posting.rejection_reason)}
              </p>
            )}

            <div role="group" aria-label="Triage" className="flex items-center gap-2 text-sm">
              {TRIAGE_VIEWS.map((option) => {
                const active = option.value === posting.triage
                return (
                  <button
                    key={option.label}
                    type="button"
                    aria-pressed={active}
                    className={cn(
                      'rounded-md border border-border px-3 py-1',
                      active ? 'bg-surface-elevated text-text-primary' : 'text-text-secondary hover:text-text-primary',
                    )}
                    onClick={() => {
                      if (!active) setTriage.mutate({ postingId: posting.posting_id, value: option.value })
                    }}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>

            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-text-tertiary">Score</dt>
                <dd>
                  <Score score={posting.score} tier={posting.tier} reasons={posting.reasons} />
                </dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Location</dt>
                <dd>
                  <LocationCell locations={posting.locations} />
                </dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Compensation</dt>
                <dd>
                  <Money
                    amountMin={posting.compensation.amount_min}
                    amountMax={posting.compensation.amount_max}
                    currency={posting.compensation.currency}
                    period={posting.compensation.period}
                  />
                </dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Visa</dt>
                <dd className="flex flex-col gap-1">
                  <VisaBadge status={posting.visa_sponsorship} />
                  {visaReason?.evidence && <span className="text-xs text-text-tertiary">“{visaReason.evidence}”</span>}
                </dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Posted</dt>
                <dd>
                  <Age postedAt={posting.posted_at} firstSeenAt={posting.first_seen_at} staleAfterDays={30} />
                </dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Closes</dt>
                <dd>
                  <Deadline closesAt={posting.closes_at} />
                </dd>
              </div>
            </dl>

            <TrackingSection key={posting.posting_id} posting={posting} />

            <LlmCorrections corrections={posting.llm_corrections} />

            {posting.reasons.length > 0 && (
              <section className="flex flex-col gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Score reasons</h3>
                <ul className="flex flex-col gap-1.5">
                  {posting.reasons.map((reason) => (
                    <li key={reason.code} className="flex items-baseline gap-2 text-sm">
                      <span className={cn('font-tabular', reason.delta >= 0 ? 'text-tier-strong' : 'text-danger')}>
                        {reason.delta >= 0 ? '+' : ''}
                        {reason.delta}
                      </span>
                      <span className="text-text-secondary">{reason.code}</span>
                      {reason.evidence && <span className="text-text-tertiary">— “{reason.evidence}”</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <AliasesNote posting={posting} />

            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Description</h3>
              <p className="whitespace-pre-wrap text-sm text-text-secondary">
                {posting.description ?? 'No description available.'}
              </p>
            </section>

            <div className="mt-auto flex flex-wrap gap-2">
              <a
                href={posting.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-surface-elevated"
              >
                Open original posting ↗
              </a>
              <a
                href={api.offerPdfUrl(posting.posting_id)}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-surface-elevated"
              >
                Offer PDF
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

type PostingDetail = components['schemas']['PostingDetailOut']

// An alias from the posting's own board is an earlier requisition of the same role:
// the posting is a repost of it (blueprint/03-INTERFACES.md §3.4, rule 4).
function AliasesNote({ posting }: { posting: PostingDetail }) {
  const earlier = posting.aliases.filter((alias) => alias.source === posting.source)
  const elsewhere = [
    ...new Set(posting.aliases.filter((alias) => alias.source !== posting.source).map((alias) => alias.source)),
  ]
  if (earlier.length === 0 && elsewhere.length === 0) return null
  const lastSeen = earlier
    .map((alias) => alias.seen_at.slice(0, 10))
    .sort()
    .at(-1)
  return (
    <div className="flex flex-col gap-0.5 text-xs text-text-tertiary">
      {earlier.length > 0 && (
        <p>
          Reposted: {earlier.length === 1 ? 'an earlier listing' : `${String(earlier.length)} earlier listings`} of
          this role, last seen {lastSeen}
        </p>
      )}
      {elsewhere.length > 0 && <p>Also on: {elsewhere.join(', ')}</p>}
    </div>
  )
}
