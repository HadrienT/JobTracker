/**
 * Display-only formatting. Amounts arrive as decimal strings (never `float`, per
 * blueprint/09-CONVENTIONS.md N2) and are never converted between currencies (N3)
 * — the origin currency is shown as-is.
 */
export function formatCompactAmount(amount: string): string {
  const value = Number(amount)
  if (!Number.isFinite(value)) return amount
  if (value >= 1000) {
    const thousands = value / 1000
    const rounded = Number.isInteger(thousands) ? String(thousands) : thousands.toFixed(1)
    return `${rounded}k`
  }
  return String(Math.round(value))
}

export function formatMoneyRange(
  amountMin: string | null,
  amountMax: string | null,
  currency: string | null,
): string | null {
  if (amountMin === null && amountMax === null) return null
  if (currency === null) return null
  const symbol = currencySymbol(currency)
  if (amountMin !== null && amountMax !== null && amountMin !== amountMax) {
    return `${symbol}${formatCompactAmount(amountMin)}–${formatCompactAmount(amountMax)}`
  }
  const single = amountMin ?? amountMax
  if (single === null) return null
  return `${symbol}${formatCompactAmount(single)}`
}

const SYMBOLS: Record<string, string> = {
  USD: '$',
  GBP: '£',
  EUR: '€',
  SGD: 'S$',
  HKD: 'HK$',
}

function currencySymbol(currency: string): string {
  return SYMBOLS[currency] ?? `${currency} `
}
