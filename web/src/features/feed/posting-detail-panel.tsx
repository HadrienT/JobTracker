import { useEffect, useRef } from 'react'
import { usePostingDetail } from '@/api/queries'
import { cn } from '@/shared/lib/cn'
import { Age } from '@/shared/ui/age'
import { Deadline } from '@/shared/ui/deadline'
import { LocationCell } from '@/shared/ui/location-cell'
import { Money } from '@/shared/ui/money'
import { Score } from '@/shared/ui/score'
import { VisaBadge } from '@/shared/ui/visa-badge'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface PostingDetailPanelProps {
  postingId: string
  onClose: () => void
}

/**
 * `/p/{id}` rendered as a real modal on top of the feed (blueprint/wp/WP10-web-feed.md
 * §5): `aria-modal`, a focus trap, focus restitution on close, `Échap` to close.
 */
export function PostingDetailPanel({ postingId, onClose }: PostingDetailPanelProps) {
  const { data: posting, isPending, isError } = usePostingDetail(postingId)
  const panelRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<Element | null>(null)

  useEffect(() => {
    previouslyFocused.current = document.activeElement
    panelRef.current?.focus()
    return () => {
      if (previouslyFocused.current instanceof HTMLElement) previouslyFocused.current.focus()
    }
  }, [])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Tab') return
      const panel = panelRef.current
      if (!panel) return
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [])

  const visaReason = posting?.reasons.find((reason) => reason.code.toLowerCase().includes('sponsor'))

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" data-testid="posting-detail-overlay">
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

            {posting.aliases.length > 0 && (
              <p className="text-xs text-text-tertiary">
                Also on: {posting.aliases.map((alias) => alias.source).join(', ')}
              </p>
            )}

            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Description</h3>
              <p className="whitespace-pre-wrap text-sm text-text-secondary">
                {posting.description ?? 'No description available.'}
              </p>
            </section>

            <a
              href={posting.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-auto self-start rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-surface-elevated"
            >
              Open original posting ↗
            </a>
          </>
        )}
      </div>
    </div>
  )
}
