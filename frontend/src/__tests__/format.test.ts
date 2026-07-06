import { describe, expect, it } from 'vitest';

import { formatPercent, sentimentLabel, sentimentTone } from '../lib/format';

describe('format helpers', () => {
  it('formats positive and negative percentages', () => {
    expect(formatPercent(12.345)).toBe('+12.35%');
    expect(formatPercent(-4.2)).toBe('-4.20%');
  });

  it('maps sentiment labels to Spanish UI labels and tones', () => {
    expect(sentimentLabel('positive')).toBe('positivo');
    expect(sentimentLabel('negative')).toBe('negativo');
    expect(sentimentTone('unknown')).toBe('neutral');
  });
});

