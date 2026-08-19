import { afterEach, describe, expect, it, vi } from 'vitest';
import { brandConflict, closeRetailerSession, connectSearchEvents, createSearchBody, forgetRetailerSession, inputMatchesRequest, startRetailerSession, validateSearch, type SearchInput } from './search';

afterEach(() => vi.unstubAllGlobals());

const valid: SearchInput = {
  query: ' Speedcat OG ', ukSize: '9', brand: ' Puma ', colourway: '',
  department: 'any', pinCode: ''
};

describe('search helpers', () => {
  it('validates inputs and builds a trimmed API request', () => {
    expect(validateSearch(valid)).toBe('');
    expect(validateSearch({ ...valid, ukSize: 'nine' })).toMatch('UK size');
    expect(validateSearch({ ...valid, pinCode: '012345' })).toMatch('PIN code');
    expect(createSearchBody(valid)).toEqual({
      query: 'Speedcat OG', uk_size: '9', brand: 'Puma', colourway: null,
      department: 'any', pin_code: null, allow_query_correction: true
    });
    expect(createSearchBody(valid, false).allow_query_correction).toBe(false);
  });

  it('routes SSE updates, completion, and closure', () => {
    const listeners = new Map<string, EventListener>();
    const close = vi.fn();
    const source = {
      addEventListener: (name: string, listener: (event: MessageEvent) => void) => { listeners.set(name, listener as EventListener); },
      close,
      onerror: null as ((event: Event) => void) | null
    };
    const update = vi.fn();
    const complete = vi.fn();
    const disconnect = vi.fn();
    connectSearchEvents('abc', { update, complete, disconnect }, (url) => {
      expect(url).toBe('/api/search/abc/events');
      return source;
    });
    listeners.get('retailer_complete')?.(new Event('retailer_complete'));
    expect(update).toHaveBeenCalledOnce();
    listeners.get('search_complete')?.(new MessageEvent('search_complete', { data: JSON.stringify({ state: 'complete' }) }));
    expect(complete).toHaveBeenCalledWith({ state: 'complete' });
    expect(close).toHaveBeenCalledOnce();
  });

  it('detects contradictory brands and compares edited inputs with the submitted snapshot', () => {
    const conflict = { ...valid, query: 'Onitsuka Mexico 66', brand: 'Nike' };
    expect(brandConflict(conflict)).toMatch('onitsuka tiger');
    expect(brandConflict({ ...conflict, brand: 'Onitsuka Tiger' })).toBe('');
    const request = createSearchBody(valid);
    expect(inputMatchesRequest(valid, request)).toBe(true);
    expect(inputMatchesRequest(valid, { ...request, allow_query_correction: false })).toBe(true);
    expect(inputMatchesRequest({ ...valid, ukSize: '10' }, request)).toBe(false);
  });

  it('keeps closing an active viewer separate from forgetting retained verification', async () => {
    const json = { status: 200, headers: { 'Content-Type': 'application/json' } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), json))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), json));
    vi.stubGlobal('fetch', fetchMock);

    await closeRetailerSession('reebok');
    await forgetRetailerSession('reebok');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/retailers/reebok/session/active', { method: 'DELETE' });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/retailers/reebok/session', { method: 'DELETE' });
  });

  it('returns the verification deadline when a retailer viewer starts', async () => {
    const payload = { viewer_url: '/viewer', expires_at: 1234, session_state: 'active' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200, headers: { 'Content-Type': 'application/json' }
    })));
    await expect(startRetailerSession('reebok', 'search-1')).resolves.toEqual(payload);
  });
});
