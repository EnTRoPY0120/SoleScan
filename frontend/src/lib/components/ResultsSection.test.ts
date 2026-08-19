import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import ResultsSection from './ResultsSection.svelte';


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
