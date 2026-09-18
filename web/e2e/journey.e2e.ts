import { expect, test } from '@playwright/test'

/**
 * The one journey that matters — blueprint/wp/WP14-quality.md §2.3: load, filter by country,
 * add a stack filter, sort by date, open a detail, favorite, reload the URL and land on the
 * same screen with the favorite still there. The assertions read the API's own responses
 * (not just the DOM), so a filter that only *looks* applied cannot pass.
 */

interface Posting {
  posting_id: string
  favorited: boolean
  tech: string[]
  first_seen_at: string
  locations: { country: string | null }[]
}
interface Page {
  items: Posting[]
  next_cursor: string | null
}

function isPostingsList(url: string, needle: string): boolean {
  const { pathname, search } = new URL(url)
  return pathname.endsWith('/postings') && search.includes(needle)
}

// The journey writes one favorite. Undo it whatever the outcome, so a re-run — and the
// visual baselines, whose first row would otherwise show a filled star — see the same data.
let favorited: string | null = null
test.afterEach(async ({ request }) => {
  if (favorited === null) return
  await request.post(`/api/postings/${favorited}/favorite`, { data: { value: false } })
  favorited = null
})

test('filter, sort, open, favorite, reload — same screen, favorite kept', async ({ page }) => {
  await page.goto('/')
  const rows = page.getByTestId('posting-row')
  await expect(rows.first()).toBeVisible()

  const filters = page.getByRole('complementary', { name: 'Filters' })

  // 1. Country: the request carries the filter AND every row it returns is in that country.
  const byCountry = page.waitForResponse((r) => isPostingsList(r.url(), 'countries=US'))
  await filters.getByRole('checkbox', { name: /^US/ }).check()
  const usPage = (await (await byCountry).json()) as Page
  expect(usPage.items.length).toBeGreaterThan(0)
  for (const posting of usPage.items) {
    expect(posting.locations.some((l) => l.country === 'US')).toBe(true)
  }
  await expect(page).toHaveURL(/countries=US/)

  // 2. Stack, on top of the country.
  const byStack = page.waitForResponse((r) => isPostingsList(r.url(), 'tech_any=python'))
  await filters.getByRole('checkbox', { name: /^python/i }).check()
  const stackPage = (await (await byStack).json()) as Page
  expect(stackPage.items.length).toBeGreaterThan(0)
  expect(stackPage.items.length).toBeLessThanOrEqual(usPage.items.length)
  for (const posting of stackPage.items) {
    expect(posting.tech).toContain('python')
    expect(posting.locations.some((l) => l.country === 'US')).toBe(true)
  }

  // 3. Sort by date: newest first-seen first.
  const bySeen = page.waitForResponse((r) => isPostingsList(r.url(), 'sort=seen'))
  await page.getByLabel('Sort').selectOption('seen')
  const seenPage = (await (await bySeen).json()) as Page
  const seenAt = seenPage.items.map((p) => p.first_seen_at)
  expect(seenAt).toEqual([...seenAt].sort().reverse())
  await expect(page).toHaveURL(/sort=seen/)

  // 4. Open the first posting's detail.
  const first = seenPage.items[0]
  if (!first) throw new Error('no posting to open')
  await rows.first().dblclick()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/p/${first.posting_id}`))
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).toBeHidden()

  favorited = first.posting_id
  // 5. Favorite it, and wait for the server to have accepted it.
  const saved = page.waitForResponse(
    (r) => r.url().includes(`/postings/${first.posting_id}/favorite`) && r.request().method() === 'POST',
  )
  await rows.first().getByRole('button', { name: 'mark favorite' }).click()
  expect((await saved).status()).toBe(204)
  await expect(rows.first().getByRole('button', { name: 'unmark favorite' })).toBeVisible()

  // 6. Reload the very same URL: same filters, same sort, same first row, still favorited.
  const urlBefore = page.url()
  await page.reload()
  expect(page.url()).toBe(urlBefore)
  await expect(page.getByLabel('Sort')).toHaveValue('seen')
  await expect(filters.getByRole('checkbox', { name: /^US/ })).toBeChecked()
  await expect(filters.getByRole('checkbox', { name: /^python/i })).toBeChecked()
  await expect(rows.first().getByRole('button', { name: 'unmark favorite' })).toBeVisible()
  await expect(page.getByTestId('posting-row').first()).toHaveAttribute('id', `posting-row-${first.posting_id}`)
})
