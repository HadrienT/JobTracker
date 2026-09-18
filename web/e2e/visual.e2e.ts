import { expect, test } from '@playwright/test'

/**
 * Reference screenshots of the density primitives — the score chip, visa badge, money,
 * age and deadline cells inside a posting row, and the filter panel — on both themes
 * (blueprint/wp/WP14-quality.md §2.4). Relative ages ("3d") depend on the clock, so the
 * browser clock is pinned to the demo database's own instant; the rows come from that
 * frozen database sorted by first-seen, so what is on screen is the same on every run.
 *
 * Baselines are per-platform (`*-linux.png`): regenerate with `scripts/e2e.sh --update`
 * after an intentional visual change, and review the diff like any other code change.
 */

const DEMO_NOW = new Date('2026-09-01T09:00:00Z')
const THEMES = ['dark', 'light'] as const

for (const theme of THEMES) {
  test(`density primitives, ${theme} theme`, async ({ page }) => {
    await page.clock.setFixedTime(DEMO_NOW)
    await page.addInitScript((t) => {
      window.localStorage.setItem('jobtracker.theme', t)
    }, theme)
    await page.goto('/?sort=seen&min_score=0')
    const rows = page.getByTestId('posting-row')
    await expect(rows.first()).toBeVisible()
    // Hover state and the tooltip portal must not leak into the reference image.
    await page.mouse.move(0, 0)

    for (const index of [0, 1, 2]) {
      await expect(rows.nth(index)).toHaveScreenshot(`row-${String(index)}-${theme}.png`)
    }
    await expect(page.getByRole('complementary', { name: 'Filters' })).toHaveScreenshot(`filters-${theme}.png`)
  })
}
