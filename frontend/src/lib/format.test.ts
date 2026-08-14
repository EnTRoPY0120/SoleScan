import { describe, expect, it } from 'vitest';
import { inr, sortOffers } from './format';

describe('offer presentation', () => {
  it('formats paise as INR', () => expect(inr(1299900)).toContain('12,999'));
  it('puts unknown shipping after known totals', () => {
    const base: any = { retailer: 'A', effective_price_paise: 100, shipping_paise: null, match_score: 1 };
    expect(sortOffers([base, {...base, retailer: 'B', effective_price_paise: 200, shipping_paise: 0}], 'price')[0].retailer).toBe('B');
  });
});

