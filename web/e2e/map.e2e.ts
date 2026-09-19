import { AxeBuilder } from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * The map tab, end to end: pins come from the API, a pin holding several postings opens a list,
 * a pin holding one goes straight to the detail, and the detail panel behaves as it does on the
 * feed (one click opens it, the dimmed area closes it). Pins are found through the API rather
 * than hard-coded, so the test states what it needs — one crowded pin, one lonely one — and
 * fails loudly if the demo database stops offering them.
 */

interface Pin {
  city: string
  country: string
  count: number
  posting_id: string | null
}

const label = (pin: Pin) => `${pin.city}, ${pin.country} — ${String(pin.count)} ${pin.count === 1 ? 'posting' : 'postings'}`

test('pins → list → detail → back to the list, and a lone pin opens its posting', async ({ page, request }) => {
  const { pins } = (await (await request.get('/api/map/pins')).json()) as { pins: Pin[] }
  const crowded = pins.reduce((a, b) => (b.count > a.count ? b : a))
  const lone = pins.find((p) => p.count === 1)
  expect(crowded.count, 'the demo DB needs a pin with several postings').toBeGreaterThan(1)
  if (!lone?.posting_id) throw new Error('the demo DB needs a pin holding exactly one posting')

  await page.goto('/map')
  await expect(page.getByTestId('map-pin').first()).toBeVisible()
  await expect(page.getByTestId('map-pin')).toHaveCount(pins.length)

  // A crowded pin: a list, as long as the pin says.
  await page.getByRole('button', { name: label(crowded) }).click()
  const drawer = page.getByRole('complementary', { name: `Postings in ${crowded.city}, ${crowded.country}` })
  await expect(drawer).toBeVisible()
  const items = drawer.getByRole('list', { name: 'Postings' }).getByRole('listitem')
  await expect(items).toHaveCount(Math.min(crowded.count, 50) + (crowded.count > 50 ? 1 : 0))

  // One click on a posting opens the detail over the map.
  await items.first().getByRole('button').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(page).toHaveURL(/\/map\/p\//)

  // The dimmed area closes it: back on the map, the list still open.
  await page.mouse.click(20, 450)
  await expect(dialog).toBeHidden()
  await expect(page).toHaveURL(/\/map(\?|$)/)
  await expect(drawer).toBeVisible()

  // A lone pin skips the list and opens its posting.
  await page.getByRole('button', { name: label(lone) }).click()
  await expect(dialog).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/map/p/${lone.posting_id}`))
})

test('a filter narrows the pins, and zooming does not resize them', async ({ page }) => {
  await page.goto('/map')
  await expect(page.getByTestId('map-pin').first()).toBeVisible()
  const before = await page.getByTestId('map-pin').count()

  await page.getByRole('complementary', { name: 'Filters' }).getByRole('checkbox', { name: /^US/ }).check()
  await expect.poll(() => page.getByTestId('map-pin').count()).toBeLessThan(before)

  // Zooming grows the map, not the pins: one stays the same size on screen.
  const pin = page.getByTestId('map-pin').first()
  const width = async () => (await pin.locator('circle').boundingBox())?.width ?? 0
  const sizeBefore = await width()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  expect(Math.abs((await width()) - sizeBefore)).toBeLessThan(1)
  await page.getByRole('button', { name: 'Reset view' }).click()
})

for (const theme of ['dark', 'light'] as const) {
  test(`the map has no serious accessibility violation (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => {
      window.localStorage.setItem('jobtracker.theme', t)
    }, theme)
    await page.goto('/map')
    await expect(page.getByTestId('map-pin').first()).toBeVisible()
    await page.getByRole('button', { name: /postings$/ }).first().click()
    await expect(page.getByRole('complementary', { name: /Postings in/ })).toBeVisible()

    const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    const serious = violations
      .filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id}: ${v.help} — ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
    expect(serious).toEqual([])
  })
}
