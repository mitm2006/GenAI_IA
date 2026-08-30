/** Presentation helpers shared by the chat and dashboard views. */

const compactCurrency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 2,
})

const plainCurrency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
})

const compactNumber = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
})

const plainNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function formatCurrency(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return Math.abs(value) >= 10000
    ? compactCurrency.format(value)
    : plainCurrency.format(value)
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return Math.abs(value) >= 100000
    ? compactNumber.format(value)
    : plainNumber.format(value)
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms)) return '—'
  return ms < 1000 ? Math.round(ms) + ' ms' : (ms / 1000).toFixed(2) + ' s'
}

/** "total_revenue" -> "Total Revenue" */
export function humanizeKey(key: string): string {
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return formatNumber(value)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

/** Column names that should be rendered as money in the data table. */
const CURRENCY_HINTS = [
  'revenue',
  'sales',
  'profit',
  'amount',
  'spend',
  'spending',
  'value',
  'cost',
  'price',
]

export function looksLikeCurrency(column: string): boolean {
  const key = column.toLowerCase()
  if (key.includes('count') || key.includes('pct') || key.includes('percent')) {
    return false
  }
  return CURRENCY_HINTS.some((hint) => key.includes(hint))
}
