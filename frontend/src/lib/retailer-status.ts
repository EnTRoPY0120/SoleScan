import type { RetailerStatus } from './types';

export function retailerStatusDetail(retailer: RetailerStatus): string {
  if (retailer.state === 'pending') return 'Waiting…';
  if (retailer.state === 'running') return 'Checking now…';
  if (retailer.state === 'partial') return `${retailer.offer_count} offer${retailer.offer_count === 1 ? '' : 's'} found · some checks incomplete`;

  switch (retailer.outcome) {
    case 'offers_found':
      return `${retailer.offer_count} exact offer${retailer.offer_count === 1 ? '' : 's'} found`;
    case 'valid_empty':
      return 'Checked — no matching offers';
    case 'verification_required':
      return 'Needs verification';
    case 'access_blocked':
      return 'Access blocked';
    case 'contract_changed':
      return 'Retailer response changed';
    case 'transport_failure':
      return 'Connection failed';
    case 'internal_failure':
      return 'Service error';
    default:
      return retailer.error || 'Retailer check unavailable';
  }
}
