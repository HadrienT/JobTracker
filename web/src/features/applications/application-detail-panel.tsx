import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/api/client'
import {
  type ApplicationDetailOut,
  type ApplicationStatus,
  useApplicationDetail,
  useArchiveOffer,
  useDeleteApplication,
  useEditApplication,
  useRecordApplicationStatus,
  useUploadApplicationFile,
} from '@/api/queries'
import { todayIso } from '@/features/applications/model'
import { StatusBadge } from '@/features/feed/status-badge'
import { STATUS_OPTIONS } from '@/features/filters/defaults'
import { useModal } from '@/shared/lib/use-modal'
import { CountryChip } from '@/shared/ui/country-chip'

const ORIGIN_LABEL: Record<ApplicationDetailOut['origin'], string> = {
  import: 'Imported from the history',
  feed: 'Recorded from the feed',
  cli: 'Added by hand',
}
const IMAGE = /\.(png|jpe?g|webp|gif)$/i
const FIELD = 'rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary'
const BUTTON =
  'rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-surface-elevated disabled:opacity-50'
const SECTION = 'flex flex-col gap-2 rounded-md border border-border p-3'
const HEADING = 'text-xs font-semibold uppercase tracking-wide text-text-secondary'

function size(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`
  if (bytes < 1024 * 1024) return `${String(Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

interface ApplicationDetailPanelProps {
  applicationId: string
  onClose: () => void
}

/** One application on top of the list: where it stands, its history, its files — all editable. */
export function ApplicationDetailPanel({ applicationId, onClose }: ApplicationDetailPanelProps) {
  const { data: application, isPending, isError } = useApplicationDetail(applicationId)
  const panelRef = useRef<HTMLDivElement>(null)
  useModal(panelRef, onClose)

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/50"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="application-detail-title"
        tabIndex={-1}
        className="flex h-full w-full max-w-2xl flex-col gap-4 overflow-y-auto border-l border-border bg-surface p-6 outline-none"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="application-detail-title" className="text-lg font-semibold text-text-primary">
            {application ? (application.title ?? '(no title)') : 'Application'}
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
        {isError && <p className="text-sm text-danger">Couldn&apos;t load this application.</p>}
        {application && <ApplicationBody application={application} onDeleted={onClose} />}
      </div>
    </div>
  )
}

function ApplicationBody({ application, onDeleted }: { application: ApplicationDetailOut; onDeleted: () => void }) {
  const id = application.application_id
  return (
    <>
      <div className="flex flex-col gap-1 text-sm text-text-secondary">
        <p>
          <span className="text-text-primary">{application.company}</span>
          {application.location && ` · ${application.location}`}
          {application.countries.map((code) => (
            <CountryChip key={code} code={code} className="ml-1.5 align-middle" />
          ))}
        </p>
        <p>
          Applied {application.applied_on ?? 'on an unknown date'}
          {application.applied_on_estimated && ' (estimated from the screenshots)'} · {ORIGIN_LABEL[application.origin]}
        </p>
        <div className="flex flex-wrap gap-3">
          {application.posting_id && (
            <a href={`/p/${encodeURIComponent(application.posting_id)}`} className="text-text-primary underline">
              Open in the feed
            </a>
          )}
          {application.posting_url && (
            <a
              href={application.posting_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-primary underline"
            >
              Original posting ↗
            </a>
          )}
        </div>
      </div>

      <StatusSection application={application} />
      <NoteSection key={`note-${id}`} application={application} />
      <FilesSection application={application} />
      <OfferSection application={application} />
      <EditSection key={`edit-${id}`} application={application} />
      <DeleteSection applicationId={id} onDeleted={onDeleted} />
    </>
  )
}

function StatusSection({ application }: { application: ApplicationDetailOut }) {
  const record = useRecordApplicationStatus()
  // No preset: recording the status it already has would be a step that says nothing.
  const [status, setStatus] = useState<ApplicationStatus | ''>('')
  const [onDate, setOnDate] = useState(todayIso())
  const [reason, setReason] = useState('')

  return (
    <section aria-label="Status" className={SECTION}>
      <h3 className={HEADING}>Where it stands</h3>
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={application.status} />
        {application.reason && <span className="text-text-secondary">{application.reason}</span>}
        {application.closed_on && <span className="text-text-tertiary">closed {application.closed_on}</span>}
      </p>
      {application.abandoned && (
        <p className="text-xs text-text-tertiary">
          No news since {application.last_news_on ?? '?'} — five months and more: counted as abandoned. Recording a new
          step reopens it.
        </p>
      )}

      <ol aria-label="History" className="flex flex-col gap-1 border-l border-border pl-3 text-sm">
        {application.events.map((event, index) => (
          <li key={index} className="flex flex-wrap gap-2">
            <span className="font-tabular text-text-tertiary">{event.on_date ?? '?'}</span>
            <StatusBadge status={event.status} />
            {event.reason && <span className="text-text-secondary">{event.reason}</span>}
          </li>
        ))}
      </ol>

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (status === '') return
          record.mutate(
            {
              applicationId: application.application_id,
              body: { status, on_date: onDate || null, reason: reason || null },
            },
            {
              onSuccess: () => {
                setReason('')
                setStatus('')
              },
            },
          )
        }}
      >
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          New step
          <select
            aria-label="New status"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as ApplicationStatus)
            }}
            className={FIELD}
          >
            <option value="" disabled>
              Choose…
            </option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          On
          <input
            type="date"
            aria-label="Date of the step"
            value={onDate}
            onChange={(event) => {
              setOnDate(event.target.value)
            }}
            className={FIELD}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-xs text-text-secondary">
          Their words (optional)
          <input
            aria-label="Reason"
            value={reason}
            placeholder="Failed 2nd interview, Job filled…"
            onChange={(event) => {
              setReason(event.target.value)
            }}
            className={FIELD}
          />
        </label>
        <button type="submit" className={BUTTON} disabled={record.isPending || status === ''}>
          Record
        </button>
      </form>
      {record.isError && <p className="text-xs text-danger">Couldn&apos;t record the step.</p>}
    </section>
  )
}

/** Saved when the field is left — and when the panel closes with the field still focused. */
function NoteSection({ application }: { application: ApplicationDetailOut }) {
  const edit = useEditApplication()
  const [draft, setDraft] = useState(application.note)
  const saved = useRef(application.note)
  const latest = useRef(draft)
  useEffect(() => {
    latest.current = draft
  })
  const { mutate } = edit
  const save = useCallback(() => {
    if (latest.current === saved.current) return
    saved.current = latest.current
    mutate({
      applicationId: application.application_id,
      body: { note: latest.current },
    })
  }, [mutate, application.application_id])
  useEffect(() => save, [save])

  return (
    <section aria-label="Note" className={SECTION}>
      <h3 className={HEADING}>Note</h3>
      <textarea
        aria-label="Application note"
        value={draft}
        rows={3}
        maxLength={4000}
        placeholder="Who you spoke to, what was said, what to do next…"
        onChange={(event) => {
          setDraft(event.target.value)
        }}
        onBlur={save}
        className={FIELD}
      />
      {edit.isError && <p className="text-xs text-danger">Couldn&apos;t save the note.</p>}
    </section>
  )
}

function FilesSection({ application }: { application: ApplicationDetailOut }) {
  const upload = useUploadApplicationFile()
  const id = application.application_id
  const images = application.files.filter((file) => IMAGE.test(file.name))
  const documents = application.files.filter((file) => !IMAGE.test(file.name))

  return (
    <section aria-label="Files" className={SECTION}>
      <h3 className={HEADING}>Files</h3>
      {application.files.length === 0 && <p className="text-sm text-text-tertiary">No file yet.</p>}
      {documents.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {documents.map((file) => (
            <li key={file.path} className="flex items-center gap-2">
              <span className="w-12 shrink-0 text-xs uppercase text-text-tertiary">{file.kind}</span>
              <a
                href={api.applicationFileUrl(id, file.path)}
                target="_blank"
                rel="noopener noreferrer"
                className="truncate text-text-primary underline"
              >
                {file.name}
              </a>
              <span className="text-xs text-text-tertiary">{size(file.size)}</span>
            </li>
          ))}
        </ul>
      )}
      {images.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {images.map((file) => (
            <a
              key={file.path}
              href={api.applicationFileUrl(id, file.path)}
              target="_blank"
              rel="noopener noreferrer"
              className="block overflow-hidden rounded-md border border-border"
            >
              <img
                src={api.applicationFileUrl(id, file.path)}
                alt={`Screenshot ${file.name}`}
                loading="lazy"
                className="h-32 w-full object-cover object-top"
              />
            </a>
          ))}
        </div>
      )}
      <label className="flex items-center gap-2 text-sm text-text-secondary">
        Attach a file (the CV sent, a letter…)
        <input
          type="file"
          aria-label="Attach a file"
          disabled={upload.isPending}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) upload.mutate({ applicationId: id, file })
            event.target.value = ''
          }}
          className="text-xs"
        />
      </label>
      {upload.isPending && <p className="text-xs text-text-tertiary">Uploading…</p>}
      {upload.isError && <p className="text-xs text-danger">Couldn&apos;t attach the file.</p>}
    </section>
  )
}

function OfferSection({ application }: { application: ApplicationDetailOut }) {
  const archive = useArchiveOffer()
  const [text, setText] = useState('')
  const hasOffer = application.files.some((file) => file.name === 'offer.pdf')
  const id = application.application_id

  return (
    <section aria-label="Offer" className={SECTION}>
      <h3 className={HEADING}>Offer PDF</h3>
      <p className="text-sm text-text-secondary">
        {hasOffer
          ? 'The offer is archived as offer.pdf (see Files).'
          : 'No offer archived yet: paste its text, and it is typeset into offer.pdf.'}
      </p>
      {application.posting_id && (
        <button
          type="button"
          className={`${BUTTON} self-start`}
          disabled={archive.isPending}
          onClick={() => {
            archive.mutate({ applicationId: id, body: {} })
          }}
        >
          {hasOffer ? 'Archive again from the posting' : 'Archive from the posting'}
        </button>
      )}
      <textarea
        aria-label="Offer text"
        value={text}
        rows={4}
        placeholder="Paste the offer's text here…"
        onChange={(event) => {
          setText(event.target.value)
        }}
        className={FIELD}
      />
      <button
        type="button"
        className={`${BUTTON} self-start`}
        disabled={archive.isPending || text.trim() === ''}
        onClick={() => {
          archive.mutate(
            { applicationId: id, body: { text, url: application.posting_url } },
            {
              onSuccess: () => {
                setText('')
              },
            },
          )
        }}
      >
        Archive from this text
      </button>
      {archive.isPending && <p className="text-xs text-text-tertiary">Typesetting…</p>}
      {archive.isError && <p className="text-xs text-danger">{archive.error.message}</p>}
    </section>
  )
}

function EditSection({ application }: { application: ApplicationDetailOut }) {
  const edit = useEditApplication()
  const [company, setCompany] = useState(application.company)
  const [title, setTitle] = useState(application.title ?? '')
  const [location, setLocation] = useState(application.location ?? '')
  const [appliedOn, setAppliedOn] = useState(application.applied_on ?? '')

  return (
    <details className={SECTION}>
      <summary className={`${HEADING} cursor-pointer`}>Fix the details</summary>
      <form
        className="grid grid-cols-2 gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          edit.mutate({
            applicationId: application.application_id,
            body: {
              company: company.trim() || null,
              title: title.trim() || null,
              location: location.trim() || null,
              applied_on: appliedOn || null,
            },
          })
        }}
      >
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Company
          <input
            value={company}
            onChange={(e) => {
              setCompany(e.target.value)
            }}
            className={FIELD}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Job title
          <input
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
            }}
            className={FIELD}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Location
          <input
            value={location}
            onChange={(e) => {
              setLocation(e.target.value)
            }}
            className={FIELD}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-secondary">
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
        <button type="submit" className={`${BUTTON} col-span-2 justify-self-start`} disabled={edit.isPending}>
          Save
        </button>
        {edit.isSuccess && <p className="col-span-2 text-xs text-text-tertiary">Saved.</p>}
        {edit.isError && <p className="col-span-2 text-xs text-danger">Couldn&apos;t save.</p>}
      </form>
    </details>
  )
}

function DeleteSection({ applicationId, onDeleted }: { applicationId: string; onDeleted: () => void }) {
  const remove = useDeleteApplication()
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="mt-auto flex items-center gap-2">
      {confirming ? (
        <>
          <button
            type="button"
            className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger hover:bg-danger/10"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate(applicationId, { onSuccess: onDeleted })
            }}
          >
            Delete for good
          </button>
          <button
            type="button"
            className={BUTTON}
            onClick={() => {
              setConfirming(false)
            }}
          >
            Keep it
          </button>
          <span className="text-xs text-text-tertiary">Its files stay on disk.</span>
        </>
      ) : (
        <button
          type="button"
          className="text-sm text-text-tertiary hover:text-danger"
          onClick={() => {
            setConfirming(true)
          }}
        >
          Delete application…
        </button>
      )}
    </div>
  )
}
