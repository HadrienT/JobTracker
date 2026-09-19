import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { describe, expect, it, vi } from 'vitest'
import { pinRadius } from '@/features/map/pin-utils'
import type { MapPin } from '@/features/map/pin-utils'
import { WorldMap } from '@/features/map/world-map'

const LONDON: MapPin = { city: 'London', country: 'GB', lat: 51.5, lon: -0.13, count: 236, posting_id: null }
const PARIS: MapPin = { city: 'Paris', country: 'FR', lat: 48.86, lon: 2.35, count: 1, posting_id: 'p-1' }

function renderMap(pins: MapPin[], selectedKey: string | null = null, onSelectPin = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <WorldMap pins={pins} selectedKey={selectedKey} onSelectPin={onSelectPin} />
    </QueryClientProvider>,
  )
  return { ...utils, onSelectPin }
}

describe('WorldMap', () => {
  it('draws one labelled button per pin, with its posting count in the name', () => {
    renderMap([LONDON, PARIS])
    expect(screen.getByRole('button', { name: 'London, GB — 236 postings' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Paris, FR — 1 posting' })).toBeInTheDocument()
  })

  it('selects a pin on click and on Enter / Space', async () => {
    const user = userEvent.setup()
    const { onSelectPin } = renderMap([LONDON, PARIS])

    await user.click(screen.getByRole('button', { name: /London/ }))
    expect(onSelectPin).toHaveBeenLastCalledWith(LONDON)

    screen.getByRole('button', { name: /Paris/ }).focus()
    await user.keyboard('{Enter}')
    expect(onSelectPin).toHaveBeenLastCalledWith(PARIS)
    await user.keyboard(' ')
    expect(onSelectPin).toHaveBeenCalledTimes(3)
  })

  it('marks the selected pin as pressed', () => {
    renderMap([LONDON, PARIS], 'GB~London')
    expect(screen.getByRole('button', { name: /London/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Paris/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('zooms with the buttons and resets', async () => {
    const user = userEvent.setup()
    const { container } = renderMap([LONDON])
    const world = () => container.querySelector('svg > g')?.getAttribute('transform') ?? ''

    expect(world()).toContain('scale(1)')
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(world()).toContain('scale(1.6)')
    await user.click(screen.getByRole('button', { name: 'Reset view' }))
    expect(world()).toContain('scale(1)')
  })

  it('never zooms out past the whole world', async () => {
    const user = userEvent.setup()
    const { container } = renderMap([LONDON])
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(container.querySelector('svg > g')?.getAttribute('transform')).toContain('scale(1)')
  })

  it('keeps a pin the same size on screen whatever the zoom', async () => {
    const user = userEvent.setup()
    renderMap([LONDON])
    const pin = () => screen.getByTestId('map-pin').getAttribute('transform') ?? ''
    expect(pin()).toContain('scale(1)')
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(pin()).toContain('scale(0.625)') // 1 / 1.6: the map grows, the pin does not
  })

  it('has no accessibility violation', async () => {
    const { container } = renderMap([LONDON, PARIS])
    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('pinRadius', () => {
  it('grows with the count but is capped', () => {
    expect(pinRadius(1)).toBe(6)
    expect(pinRadius(4)).toBeLessThan(pinRadius(100))
    expect(pinRadius(1_000_000)).toBe(18)
  })
})
