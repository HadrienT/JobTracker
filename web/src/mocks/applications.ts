import { HttpResponse, http } from 'msw'
import type { components } from '@/api/schema.gen'

type Schemas = components['schemas']
type Detail = Schemas['ApplicationDetailOut']

/**
 * `/applications` for the mock API (blueprint/wp/WP21-applications.md §6): a handful of
 * fictional applications covering every case the tab draws — open, abandoned (no news for five
 * months), rejected after an interview, typed in by hand, with screenshots and a CV — held in
 * memory so a test can record a step and read it back. Reset after every test.
 */

const API_BASE = '*'

function application(overrides: Partial<Detail> & Pick<Detail, 'application_id' | 'company'>): Detail {
  return {
    company_slug: null,
    title: 'Quantitative Developer',
    location: 'UK (London)',
    applied_on: '2026-10-07',
    applied_on_estimated: false,
    closed_on: null,
    status: 'applied',
    reason: '',
    posting_id: null,
    origin: 'import',
    note: '',
    open: true,
    abandoned: false,
    last_news_on: '2026-10-07',
    reached_interview: false,
    countries: ['GB'],
    events: [{ on_date: '2026-10-07', status: 'applied', reason: '' }],
    files: [],
    dossier: null,
    posting_title: null,
    posting_url: null,
    cv_id: null,
    cv_source: null,
    ...overrides,
  }
}

function cvFixtures(): Schemas['CvOut'][] {
  return [
    {
      cv_id: 'cv-tailored',
      label: 'Tailspin — Junior QR',
      file_name: 'CV_Tailspin.pdf',
      size: 70_000,
      pinned: false,
      created_at: '2026-10-18T00:00:00Z',
      applications: 0,
      current: false,
    },
    {
      cv_id: 'cv-v2',
      label: 'v2',
      file_name: 'CV_v2.pdf',
      size: 80_000,
      pinned: true,
      created_at: '2026-10-13T00:00:00Z',
      applications: 2,
      current: true,
    },
    {
      cv_id: 'cv-v1',
      label: 'v1',
      file_name: 'CV_v1.pdf',
      size: 80_000,
      pinned: true,
      created_at: '2026-09-01T00:00:00Z',
      applications: 1,
      current: false,
    },
  ]
}

function fixtures(): Detail[] {
  return [
    application({
      application_id: 'app-open',
      company: 'Northwind Capital',
      cv_id: 'cv-v2',
      cv_source: 'confirmed',
      dossier: 'Northwind Capital/Quant Dev London',
      files: [
        {
          name: '1.png',
          path: 'Northwind Capital/Quant Dev London/1.png',
          kind: 'offer',
          size: 120_000,
        },
        {
          name: 'CV.pdf',
          path: 'Northwind Capital/Quant Dev London/CV.pdf',
          kind: 'cv',
          size: 80_000,
        },
      ],
    }),
    application({
      application_id: 'app-abandoned',
      company: 'Contoso Trading',
      title: null,
      location: 'CH (Zurich)',
      countries: ['CH'],
      applied_on: '2024-11-15',
      last_news_on: '2024-11-15',
      reason: 'Waiting for answer',
      open: false,
      abandoned: true,
      events: [{ on_date: '2024-11-15', status: 'applied', reason: '' }],
    }),
    application({
      application_id: 'app-rejected',
      company: 'Fabrikam Securities',
      cv_id: 'cv-v1',
      cv_source: 'confirmed',
      title: 'C++ Developer',
      location: 'USA (Chicago) IL',
      countries: ['US'],
      applied_on: '2026-09-01',
      closed_on: '2026-09-21',
      status: 'rejected',
      reason: 'Failed 2nd interview',
      open: false,
      reached_interview: true,
      last_news_on: '2026-09-21',
      events: [
        { on_date: '2026-09-01', status: 'applied', reason: '' },
        { on_date: '2026-09-10', status: 'interview', reason: '' },
        {
          on_date: '2026-09-21',
          status: 'rejected',
          reason: 'Failed 2nd interview',
        },
      ],
    }),
    application({
      application_id: 'app-by-hand',
      company: 'Tailspin Research',
      cv_id: 'cv-v2',
      cv_source: 'inferred',
      title: 'Junior Quant Researcher',
      location: 'Singapore',
      countries: ['SG'],
      applied_on: '2026-10-18',
      origin: 'cli',
      note: 'referral',
      last_news_on: '2026-10-18',
      events: [{ on_date: '2026-10-18', status: 'applied', reason: '' }],
    }),
  ]
}

let store = new Map<string, Detail>()
let cvs = new Map<string, Schemas['CvOut']>()

export function resetApplications(): void {
  store = new Map(fixtures().map((a) => [a.application_id, a]))
  cvs = new Map(cvFixtures().map((cv) => [cv.cv_id, cv]))
}
resetApplications()

const SUMMARY_FIELDS = [
  'application_id',
  'company',
  'company_slug',
  'title',
  'location',
  'applied_on',
  'applied_on_estimated',
  'closed_on',
  'status',
  'reason',
  'posting_id',
  'origin',
  'note',
  'open',
  'abandoned',
  'last_news_on',
  'reached_interview',
  'countries',
  'cv_id',
  'cv_source',
] as const

function summary(detail: Detail): Schemas['ApplicationOut'] {
  return Object.fromEntries(SUMMARY_FIELDS.map((key) => [key, detail[key]])) as Schemas['ApplicationOut']
}

function notFound(id: unknown) {
  return HttpResponse.json({ detail: `no such application: '${String(id)}'` }, { status: 404 })
}

export const applicationHandlers = [
  http.get(`${API_BASE}/applications`, () =>
    HttpResponse.json(
      [...store.values()].sort((a, b) => (b.applied_on ?? '').localeCompare(a.applied_on ?? '')).map(summary),
    ),
  ),

  http.get(`${API_BASE}/applications/:id`, ({ params }) => {
    const found = store.get(String(params.id))
    return found ? HttpResponse.json(found) : notFound(params.id)
  }),

  http.post(`${API_BASE}/applications`, async ({ request }) => {
    const body = (await request.json()) as Schemas['ApplicationCreate']
    const appliedOn = body.applied_on ?? '2026-10-21'
    const id = `app-${String(store.size + 1)}`
    const offer = body.offer_text
      ? [
          {
            name: 'offer.pdf',
            path: `${id}/offer.pdf`,
            kind: 'offer',
            size: 30_000,
          },
        ]
      : []
    const created = application({
      application_id: id,
      company: body.company,
      title: body.title,
      location: body.location ?? null,
      countries: [],
      applied_on: appliedOn,
      status: body.status,
      note: body.note,
      origin: 'cli',
      last_news_on: appliedOn,
      events: [{ on_date: appliedOn, status: 'applied', reason: '' }],
      files: offer,
      dossier: id,
      cv_id: body.cv_id ?? null,
      cv_source: body.cv_id ? 'confirmed' : null,
    })
    store.set(id, created)
    return HttpResponse.json(created, { status: 201 })
  }),

  http.post(`${API_BASE}/applications/:id/status`, async ({ params, request }) => {
    const found = store.get(String(params.id))
    if (!found) return notFound(params.id)
    const body = (await request.json()) as Schemas['ApplicationStatusRequest']
    const closing = body.status === 'rejected' || body.status === 'withdrawn'
    const updated: Detail = {
      ...found,
      status: body.status,
      reason: body.reason ?? found.reason,
      closed_on: closing ? (body.on_date ?? null) : null,
      open: body.status === 'applied' || body.status === 'interview',
      abandoned: false,
      reached_interview: found.reached_interview || body.status === 'interview' || body.status === 'offer',
      events: [
        ...found.events,
        {
          on_date: body.on_date ?? null,
          status: body.status,
          reason: body.reason ?? '',
        },
      ],
    }
    store.set(found.application_id, updated)
    return HttpResponse.json(updated)
  }),

  http.post(`${API_BASE}/applications/:id/edit`, async ({ params, request }) => {
    const found = store.get(String(params.id))
    if (!found) return notFound(params.id)
    const body = (await request.json()) as Schemas['ApplicationEditRequest']
    const changes = Object.fromEntries(Object.entries(body).filter(([, value]) => value !== null))
    const updated: Detail = { ...found, ...changes }
    store.set(found.application_id, updated)
    return HttpResponse.json(updated)
  }),

  http.post(`${API_BASE}/applications/:id/cv`, async ({ params, request }) => {
    const found = store.get(String(params.id))
    if (!found) return notFound(params.id)
    const { cv_id: cvId } = (await request.json()) as Schemas['ApplicationCvRequest']
    const updated: Detail = { ...found, cv_id: cvId, cv_source: cvId === null ? null : 'confirmed' }
    store.set(found.application_id, updated)
    return HttpResponse.json(updated)
  }),

  http.get(`${API_BASE}/cvs`, () => HttpResponse.json([...cvs.values()])),

  http.post(`${API_BASE}/cvs`, async ({ request }) => {
    const name = new URL(request.url).searchParams.get('name') ?? 'cv.pdf'
    const data = await request.arrayBuffer()
    if (new TextDecoder().decode(data.slice(0, 5)) !== '%PDF-') {
      return HttpResponse.json({ detail: `not a PDF: '${name}'` }, { status: 422 })
    }
    const cv: Schemas['CvOut'] = {
      cv_id: `cv-${String(cvs.size + 1)}`,
      label: name.replace(/\.pdf$/, ''),
      file_name: name,
      size: data.byteLength,
      pinned: true,
      created_at: '2026-10-21T00:00:00Z',
      applications: 0,
      current: false,
    }
    cvs.set(cv.cv_id, cv)
    return HttpResponse.json(cv, { status: 201 })
  }),

  http.post(`${API_BASE}/cvs/:id/edit`, async ({ params, request }) => {
    const found = cvs.get(String(params.id))
    if (!found) return HttpResponse.json({ detail: 'no such CV' }, { status: 404 })
    const body = (await request.json()) as Schemas['CvEditRequest']
    const updated = { ...found, label: body.label ?? found.label, pinned: body.pinned ?? found.pinned }
    cvs.set(found.cv_id, updated)
    return HttpResponse.json(updated)
  }),

  http.post(`${API_BASE}/applications/:id/delete`, ({ params }) => {
    if (!store.delete(String(params.id))) return notFound(params.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API_BASE}/applications/:id/offer`, async ({ params, request }) => {
    const found = store.get(String(params.id))
    if (!found) return notFound(params.id)
    const body = (await request.json()) as Schemas['OfferTextRequest']
    if (!body.text && found.posting_id === null) {
      return HttpResponse.json(
        {
          detail: 'no offer to archive: paste its text, or link its posting',
        },
        { status: 422 },
      )
    }
    const path = `${found.dossier ?? found.application_id}/offer.pdf`
    const files = [
      ...found.files.filter((f) => f.name !== 'offer.pdf'),
      { name: 'offer.pdf', path, kind: 'offer', size: 30_000 },
    ]
    const updated = { ...found, files }
    store.set(found.application_id, updated)
    return HttpResponse.json(updated)
  }),

  http.post(`${API_BASE}/applications/:id/files`, async ({ params, request }) => {
    const found = store.get(String(params.id))
    if (!found) return notFound(params.id)
    const name = new URL(request.url).searchParams.get('name') ?? 'file'
    const size = (await request.arrayBuffer()).byteLength
    const file = {
      name,
      path: `${found.dossier ?? found.application_id}/${name}`,
      kind: 'cv',
      size,
    }
    store.set(found.application_id, {
      ...found,
      files: [...found.files, file],
    })
    return HttpResponse.json(file, { status: 201 })
  }),

  http.get(
    `${API_BASE}/applications/:id/files/*`,
    () =>
      new HttpResponse(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
        headers: { 'content-type': 'application/pdf' },
      }),
  ),
]
