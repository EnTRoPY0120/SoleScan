import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import ResultsSection from './ResultsSection.svelte';
import type { RetailerStatus } from '$lib/types';


describe('resolved query notice', () => {
  it('renders the resolved identity and an original-text action', () => {
    const { body } = render(ResultsSection, {
      props: {
        visible: true,
        resultRequest: {
          query: 'onitsuka mexio 66', uk_size: '9', allow_query_correction: true,
          brand: null, colourway: null, department: 'any', pin_code: null
        },
        resolvedQuery: 'onitsuka mexico 66',
        searchOriginal: () => undefined,
        refresh: () => undefined
      }
    });

    expect(body).toContain('Showing results for');
    expect(body).toContain('onitsuka mexico 66');
    expect(body).toContain('Search original text');
  });
});


describe('verification lifecycle', () => {
  it('shows only the active-session actions with a deadline', () => {
    const retailer: RetailerStatus = {
      retailer_id: 'reebok', retailer: 'Reebok India', state: 'needs_session',
      offer_count: 0, error: null, elapsed_ms: 100, reason_code: 'verification_challenge',
      http_status: null, retry_count: 0, circuit_state: 'open', source: null,
      retry_at: null, session_capable: true, session_state: 'active',
      outcome: 'verification_required'
    };
    const { body } = render(ResultsSection, {
      props: {
        visible: true,
        sectionRetailers: [retailer],
        activeRetailerId: 'reebok',
        sessionSecondsRemaining: 420,
        refresh: () => undefined
      }
    });

    expect(body).toContain('I cleared verification');
    expect(body).toContain('Close without saving');
    expect(body).toContain('7:00 remaining');
    expect(body).not.toContain('Open retailer verification');
  });
});
