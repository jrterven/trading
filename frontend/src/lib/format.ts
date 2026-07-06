export function formatCurrency(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '$0.00';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value?: number | null, digits = 2): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '0';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatPercent(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '0.00%';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function sentimentLabel(label: string): string {
  if (label === 'positive') return 'positivo';
  if (label === 'negative') return 'negativo';
  return 'neutral';
}

export function sentimentTone(label?: string): 'positive' | 'negative' | 'neutral' {
  if (label === 'positive') return 'positive';
  if (label === 'negative') return 'negative';
  return 'neutral';
}

export function toDateInput(date: Date): string {
  return date.toISOString().slice(0, 10);
}

