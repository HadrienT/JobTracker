import { AxeBuilder } from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

/**
 * `axe` on the three screens of blueprint/wp/WP14-quality.md §2.4, in both themes — contrast
 * is theme-dependent, so one theme passing says nothing about the other. Serious and
 * critical violations fail; anything milder is reported in the failure message only when
 * one of those is also present, because a suite that is red for a nit gets disabled.
 */

const THEMES = ['dark', 'light'] as const

async function seriousViolations(page: Page, include?: string) {
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
  if (include) builder = builder.include(include)
  const { violations } = await builder.analyze()
  return violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id} (${String(v.impact)}): ${v.help} — ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
}

for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t) => {
        window.localStorage.setItem('jobtracker.theme', t)
      }, theme)
      await page.goto('/')
      await expect(page.getByTestId('posting-row').first()).toBeVisible()
    })

    test('the feed has no serious accessibility violation', async ({ page }) => {
      expect(await seriousViolations(page, '[role="grid"]')).toEqual([])
    })

    test('the filters panel has no serious accessibility violation', async ({ page }) => {
      expect(await seriousViolations(page, 'aside[aria-label="Filters"]')).toEqual([])
    })

    test('the detail panel has no serious accessibility violation', async ({ page }) => {
      await page.getByTestId('posting-row').first().click()
      await expect(page.getByRole('dialog')).toBeVisible()
      expect(await seriousViolations(page, '[role="dialog"]')).toEqual([])
    })
  })
}
