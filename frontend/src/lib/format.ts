import type { Offer } from './types';

export const inr = (paise: number) => new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: paise % 100 ? 2 : 0
}).format(paise / 100);

export function sortOffers(offers: Offer[], sort: string): Offer[] {
  return [...offers].sort((a, b) => {
    const stockOrder = { in_stock: 0, unknown: 1, out_of_stock: 2 };
    const stock = stockOrder[a.stock_status] - stockOrder[b.stock_status];
    if (stock) return stock;
    if (sort === 'match') return b.match_score - a.match_score;
    if (sort === 'retailer') return a.retailer.localeCompare(b.retailer);
    const unknown = Number(a.shipping_paise === null) - Number(b.shipping_paise === null);
    return unknown || a.effective_price_paise - b.effective_price_paise;
  });
}
