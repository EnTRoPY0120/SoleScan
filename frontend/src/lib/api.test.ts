import { describe, expect, it } from 'vitest';
import { apiJson } from './api';

describe('apiJson', () => {
  it('returns successful JSON', async () => {
    const response = new Response(JSON.stringify({ id: 'search-id' }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' }
    });
    await expect(apiJson(response, 'Could not search.')).resolves.toEqual({ id: 'search-id' });
  });

  it('uses a structured API error', async () => {
    const response = new Response(JSON.stringify({ detail: 'Storage is unavailable.' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
    await expect(apiJson(response, 'Could not search.')).rejects.toThrow('Storage is unavailable.');
  });

  it('does not expose a JSON parser error for plain-text failures', async () => {
    const response = new Response('Internal Server Error', {
      status: 500,
      headers: { 'Content-Type': 'text/plain' }
    });
    await expect(apiJson(response, 'Could not search.')).rejects.toThrow('Could not search. (HTTP 500)');
  });
});
