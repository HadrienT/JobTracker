import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { contrastRatio } from '@/shared/lib/contrast'

const css = readFileSync(join(import.meta.dirname, 'theme.css'), 'utf-8')

function extractBlock(css_: string, selector: string): Record<string, string> {
  const start = css_.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`selector not found: ${selector}`)
  const end = css_.indexOf('}', start)
  const block = css_.slice(start, end)
  const tokens: Record<string, string> = {}
  for (const match of block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    const name = match[1]
    const value = match[2]
    if (name && value) tokens[name] = value
  }
  return tokens
}

const dark = extractBlock(css, ':root')
const light = extractBlock(css, ":root[data-theme='light']")

const TEXT_ON_SURFACE_PAIRS: [text: string, surface: string][] = [
  ['text-primary', 'background'],
  ['text-primary', 'surface'],
  ['text-secondary', 'background'],
  ['text-secondary', 'surface'],
]

describe('theme tokens', () => {
  it('defines every dark token again for light', () => {
    expect(Object.keys(light).sort()).toEqual(Object.keys(dark).sort())
  })

  it.each(TEXT_ON_SURFACE_PAIRS)('dark: %s on %s passes WCAG AA (>= 4.5:1)', (text, surface) => {
    const textValue = dark[text]
    const surfaceValue = dark[surface]
    if (!textValue || !surfaceValue) throw new Error('missing token')
    expect(contrastRatio(textValue, surfaceValue)).toBeGreaterThanOrEqual(4.5)
  })

  it.each(TEXT_ON_SURFACE_PAIRS)('light: %s on %s passes WCAG AA (>= 4.5:1)', (text, surface) => {
    const textValue = light[text]
    const surfaceValue = light[surface]
    if (!textValue || !surfaceValue) throw new Error('missing token')
    expect(contrastRatio(textValue, surfaceValue)).toBeGreaterThanOrEqual(4.5)
  })

  it('text-tertiary stays legible (>= 3:1, it is the Empty-value tone) in both themes', () => {
    const darkTertiary = dark['text-tertiary']
    const darkBg = dark.background
    const lightTertiary = light['text-tertiary']
    const lightBg = light.background
    if (!darkTertiary || !darkBg || !lightTertiary || !lightBg) throw new Error('missing token')
    expect(contrastRatio(darkTertiary, darkBg)).toBeGreaterThanOrEqual(3)
    expect(contrastRatio(lightTertiary, lightBg)).toBeGreaterThanOrEqual(3)
  })
})
