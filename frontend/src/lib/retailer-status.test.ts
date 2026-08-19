import { describe, expect, it } from 'vitest';
import { retailerStatusDetail } from './retailer-status';
import type { RetailerStatus } from './types';

function status(outcome: RetailerStatus['outcome'], offer_count = 0): RetailerStatus {
  return {
    retailer_id: 'store', retailer: 'Store', state: 'error', offer_count, error: 'technical detail',
    elapsed_ms: 1, reason_code: 'implementation_detail', http_status: null, retry_count: 0,
    circuit_state: 'closed', source: null, retry_at: null, session_capable: false,
    session_state: 'none', outcome,
  };
}

describe('retailer status language', () => {
  it('uses stable shopper language instead of low-level reason codes', () => {
    expect(retailerStatusDetail(status('valid_empty'))).toBe('Checked — no matching offers');
    expect(retailerStatusDetail(status('contract_changed'))).toBe('Retailer response changed');
    expect(retailerStatusDetail(status('transport_failure'))).toBe('Connection failed');
    expect(retailerStatusDetail(status('verification_required'))).toBe('Needs verification');
  });
});
