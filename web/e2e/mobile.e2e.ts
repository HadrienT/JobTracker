import { expect, test } from '@playwright/test'

/**
 * A phone held upright. The failure this guards against is quiet: one fixed-width element (a
 * 288px panel, an eleven-column grid) and the browser zooms the whole page out to fit it, every
 * screen turning unreadable at once. So each tab must fit the viewport's width, and the feed —
 * the screen actually used on a phone — must read as rows, with its filters one tap away.
 */

const PHONE_WIDTH = 390

test.use({ viewport: { width: PHONE_WIDTH, height: 844 }, isMobile: true, hasTouch: true })

for (const path of ['/', '/ch', '/tech', '/applications', '/map', '/companies', '/health']) {
  test(`${path} fits a phone's width`, async ({ page }) => {
    await page.goto(path)
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    // Not against `innerWidth`: a mobile browser widens its layout viewport to whatever overflows,
    // so the two always agree. The phone's own width is the yardstick.
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(scrollWidth).toBeLessThanOrEqual(PHONE_WIDTH)
  })
}

test('the feed hides its filters behind a button, and Done brings the postings back', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('posting-row').first()).toBeVisible()
  const filters = page.getByRole('complementary', { name: 'Filters' })
  await expect(filters).toBeHidden()

  await page.getByRole('button', { name: /^Filters/ }).click()
  await expect(filters).toBeVisible()
  await filters.getByRole('checkbox').first().check()

  await page.getByRole('button', { name: 'Done' }).click()
  await expect(filters).toBeHidden()
  await expect(page.getByRole('list', { name: 'Active filters' })).toBeVisible()
  await expect(page.getByTestId('posting-row').first()).toBeVisible()
})
