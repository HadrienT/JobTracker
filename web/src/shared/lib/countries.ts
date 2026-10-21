/**
 * A country, coloured as the user coloured the spreadsheet's cells (blueprint/wp/WP21-applications.md
 * §6): Switzerland red, UK blue, USA orange, Singapore and Hong Kong pink, Netherlands green — then a
 * hue of its own for the other usual ones, grey for the rest. Classes are written out in full so
 * Tailwind sees every one of them.
 */
export const COUNTRY_TONES: Record<string, { chip: string; tint: string }> = {
  CH: { chip: 'border-country-ch/60 bg-country-ch/15 text-country-ch', tint: 'bg-country-ch/10' },
  GB: { chip: 'border-country-gb/60 bg-country-gb/15 text-country-gb', tint: 'bg-country-gb/10' },
  US: { chip: 'border-country-us/60 bg-country-us/15 text-country-us', tint: 'bg-country-us/10' },
  SG: { chip: 'border-country-asia/60 bg-country-asia/15 text-country-asia', tint: 'bg-country-asia/10' },
  HK: { chip: 'border-country-asia/60 bg-country-asia/15 text-country-asia', tint: 'bg-country-asia/10' },
  NL: { chip: 'border-country-nl/60 bg-country-nl/15 text-country-nl', tint: 'bg-country-nl/10' },
  DE: { chip: 'border-country-de/60 bg-country-de/15 text-country-de', tint: 'bg-country-de/10' },
  FR: { chip: 'border-country-fr/60 bg-country-fr/15 text-country-fr', tint: 'bg-country-fr/10' },
  CA: { chip: 'border-country-ca/60 bg-country-ca/15 text-country-ca', tint: 'bg-country-ca/10' },
  CN: { chip: 'border-country-cn/60 bg-country-cn/15 text-country-cn', tint: 'bg-country-cn/10' },
}
export const OTHER_TONE = { chip: 'border-country-other/60 bg-country-other/15 text-country-other', tint: '' }

let names: Intl.DisplayNames | null = null

export function countryName(code: string): string {
  try {
    names ??= new Intl.DisplayNames(['en'], { type: 'region' })
    return names.of(code) ?? code
  } catch {
    return code // an engine without region names: the code is still a fair label
  }
}

/** The light background of a location cell, after its first country — like the sheet's. */
export function countryTint(code: string | undefined): string {
  return code === undefined ? '' : (COUNTRY_TONES[code] ?? OTHER_TONE).tint
}
