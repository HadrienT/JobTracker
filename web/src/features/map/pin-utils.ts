import type { components } from '@/api/schema.gen'

export type MapPin = components['schemas']['MapPin']

/** Pin radius in screen-ish pixels: area follows the count, capped so New York cannot eat the map. */
export function pinRadius(count: number): number {
  return count === 1 ? 6 : Math.min(18, 5 + 0.9 * Math.sqrt(count))
}

export function pinKey(pin: { country: string; city: string }): string {
  return `${pin.country}~${pin.city}`
}
