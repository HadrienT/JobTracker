import { useRef, useState } from 'react'
import { type ApplicationStatus, useCreateApplication, useCvs } from '@/api/queries'
import { todayIso } from '@/features/applications/model'
import { STATUS_OPTIONS } from '@/features/filters/defaults'
import { useModal } from '@/shared/lib/use-modal'

const FIELD = 'rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary'
const LABEL = 'flex flex-col gap-1 text-xs text-text-secondary'

interface NewApplicationDialogProps {
  onClose: () => void
  onCreated: (applicationId: string) => void
}

/**
 * An application made outside the feed: an offer seen elsewhere, a recruiter's email, a
 * referral. The offer's text, pasted, is typeset into offer.pdf; a URL the collector already
 * knows links the posting instead (blueprint/wp/WP21-applications.md §2bis).
 */
export function NewApplicationDialog({ onClose, onCreated }: NewApplicationDialogProps) {
  const create = useCreateApplication()
  const panelRef = useRef<HTMLFormElement>(null)
  useModal(panelRef, onClose)
  const [company, setCompany] = useState('')
  const [title, setTitle] = useState('')
  const [location, setLocation] = useState('')
  const [url, setUrl] = useState('')
  const [appliedOn, setAppliedOn] = useState(todayIso())
  const [status, setStatus] = useState<ApplicationStatus>('applied')
  const [note, setNote] = useState('')
  const [offerText, setOfferText] = useState('')
  const cvs = useCvs()
  const versions = (cvs.data ?? []).filter((cv) => cv.pinned)
  // Untouched, the menu shows the version in use: that is what the user sends by submitting.
  const [chosenCv, setChosenCv] = useState<string | null>(null)
  const cvId = chosenCv ?? versions.find((cv) => cv.current)?.cv_id ?? ''

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-2 md:p-6"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <form
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-application-title"
        tabIndex={-1}
        className="flex w-full max-w-xl flex-col gap-3 rounded-md border border-border bg-surface p-4 outline-none md:p-6"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate(
            {
              company: company.trim(),
              title: title.trim(),
              location: location.trim() || null,
              url: url.trim() || null,
              applied_on: appliedOn || null,
              status,
              note,
              offer_text: offerText.trim() || null,
              // Still loading: left out, the server assumes the version in use.
              ...(cvs.data && { cv_id: cvId || null }),
            },
            {
              onSuccess: (detail) => {
                onCreated(detail.application_id)
              },
            },
          )
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="new-application-title" className="text-lg font-semibold text-text-primary">
            New application
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

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className={LABEL}>
            Company *
            <input
              required
              value={company}
              onChange={(e) => {
                setCompany(e.target.value)
              }}
              className={FIELD}
            />
          </label>
          <label className={LABEL}>
            Job title *
            <input
              required
              value={title}
              onChange={(e) => {
                setTitle(e.target.value)
              }}
              className={FIELD}
            />
          </label>
          <label className={LABEL}>
            Location
            <input
              value={location}
              onChange={(e) => {
                setLocation(e.target.value)
              }}
              className={FIELD}
            />
          </label>
          <label className={LABEL}>
            Applied on
            <input
              type="date"
              value={appliedOn}
              onChange={(e) => {
                setAppliedOn(e.target.value)
              }}
              className={FIELD}
            />
          </label>
          <label className={`${LABEL} col-span-2`}>
            Offer URL
            <input
              type="url"
              value={url}
              placeholder="https://…"
              onChange={(e) => {
                setUrl(e.target.value)
              }}
              className={FIELD}
            />
          </label>
          <label className={LABEL}>
            Status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as ApplicationStatus)
              }}
              className={FIELD}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL}>
            CV sent
            <select
              value={cvId}
              onChange={(e) => {
                setChosenCv(e.target.value)
              }}
              className={FIELD}
            >
              <option value="">Not recorded</option>
              {versions.map((cv) => (
                <option key={cv.cv_id} value={cv.cv_id}>
                  {cv.label}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL}>
            Note
            <input
              value={note}
              onChange={(e) => {
                setNote(e.target.value)
              }}
              className={FIELD}
            />
          </label>
          <label className={`${LABEL} col-span-2`}>
            Offer text — pasted, it becomes a clean offer.pdf
            <textarea
              rows={8}
              value={offerText}
              onChange={(e) => {
                setOfferText(e.target.value)
              }}
              className={FIELD}
            />
          </label>
        </div>

        {create.isError && <p className="text-sm text-danger">{create.error.message}</p>}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary hover:bg-surface-elevated"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={create.isPending}
            className="rounded-md border border-text-secondary bg-surface-elevated px-3 py-1.5 text-sm text-text-primary disabled:opacity-50"
          >
            Record the application
          </button>
        </div>
      </form>
    </div>
  )
}
