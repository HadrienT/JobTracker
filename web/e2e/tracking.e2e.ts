import { expect, test } from '@playwright/test'

/**
 * Application tracking, end to end (blueprint/wp/WP18-tracking.md): set a status and a note in the
 * detail panel, see the badge on the row, filter on it, reload and find everything still there.
 * The demo database is shared by the whole run, so the test puts back what it changed.
 */

let touched: string | null = null
test.afterEach(async ({ request }) => {
  if (touched === null) return
  await request.post(`/api/postings/${touched}/status`, { data: { status: null } })
  await request.post(`/api/postings/${touched}/note`, { data: { note: '' } })
  touched = null
})

test('status and note: set, seen on the row, filterable, still there after a reload', async ({ page, request }) => {
  await page.goto('/')
  const rows = page.getByTestId('posting-row')
  await expect(rows.first()).toBeVisible()
  const firstTitle = (await rows.first().getAttribute('id')) ?? ''
  const id = firstTitle.replace('posting-row-', '')
  touched = id

  // Open the detail and track the application.
  await rows.first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const saved = page.waitForResponse((r) => r.url().includes(`/postings/${id}/status`) && r.request().method() === 'POST')
  await dialog.getByRole('combobox', { name: 'Application status' }).selectOption('interview')
  expect((await saved).status()).toBe(204)

  // A note, saved by leaving the field.
  const note = dialog.getByRole('textbox', { name: 'Notes' })
  const noteSaved = page.waitForResponse((r) => r.url().includes(`/postings/${id}/note`) && r.request().method() === 'POST')
  await note.fill('second round on the 12th')
  await note.blur()
  expect((await noteSaved).status()).toBe(204)

  // Closed by the dimmed area: the row now carries its status.
  await page.mouse.click(20, 450)
  await expect(dialog).toBeHidden()
  await expect(rows.first().getByText('Interview')).toBeVisible()

  // The Tracking filter narrows the feed to it (and only it).
  await page.getByRole('complementary', { name: 'Filters' }).getByRole('checkbox', { name: 'Interview' }).check()
  await expect(page).toHaveURL(/statuses=interview/)
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toHaveAttribute('id', `posting-row-${id}`)

  // Reload: same filter, same row, and the note is back in the detail.
  await page.reload()
  await expect(rows).toHaveCount(1)
  await rows.first().click()
  await expect(page.getByRole('combobox', { name: 'Application status' })).toHaveValue('interview')
  await expect(page.getByRole('textbox', { name: 'Notes' })).toHaveValue('second round on the 12th')

  // The API agrees with what the page shows.
  const detail = (await (await request.get(`/api/postings/${id}`)).json()) as { application_status: string; note: string }
  expect(detail).toMatchObject({ application_status: 'interview', note: 'second round on the 12th' })
})

test('a note typed and abandoned with Escape is not lost', async ({ page, request }) => {
  await page.goto('/')
  const rows = page.getByTestId('posting-row')
  await expect(rows.first()).toBeVisible()
  const id = ((await rows.first().getAttribute('id')) ?? '').replace('posting-row-', '')
  touched = id

  await rows.first().click()
  const note = page.getByRole('textbox', { name: 'Notes' })
  const saved = page.waitForResponse((r) => r.url().includes(`/postings/${id}/note`) && r.request().method() === 'POST')
  await note.fill('typed, never blurred')
  await page.keyboard.press('Escape') // closes the panel with the field still focused
  expect((await saved).status()).toBe(204)

  const detail = (await (await request.get(`/api/postings/${id}`)).json()) as { note: string }
  expect(detail.note).toBe('typed, never blurred')
})
