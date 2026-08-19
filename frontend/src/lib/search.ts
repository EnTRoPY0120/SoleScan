import { apiJson } from './api';
import type { SearchResult } from './types';

export type SearchInput = {
  query: string;
  ukSize: string;
  brand: string;
  colourway: string;
  department: string;
  pinCode: string;
};

export function validateSearch(input: SearchInput): string {
  if (input.query.trim().length < 2) return 'Enter at least two characters for the sneaker model.';
  if (!/^\s*(?:uk\s*)?\d{1,2}(?:\.5|½)?\s*$/i.test(input.ukSize)) return 'Enter a UK size such as 8 or 8.5.';
  if (input.pinCode && !/^[1-9]\d{5}$/.test(input.pinCode)) return 'Enter a valid six-digit Indian PIN code.';
  return '';
}

export function createSearchBody(input: SearchInput, allowQueryCorrection = true) {
  return {
    query: input.query.trim(),
    uk_size: input.ukSize.trim(),
    allow_query_correction: allowQueryCorrection,
    brand: input.brand.trim() || null,
    colourway: input.colourway.trim() || null,
    department: input.department,
    pin_code: input.pinCode || null
  };
}

const brandAliases: Record<string, string[]> = {
  nike: ['nike', 'jordan', 'air jordan'],
  adidas: ['adidas', 'yeezy'],
  puma: ['puma'],
  'new balance': ['new balance'],
  converse: ['converse', 'chuck taylor'],
  'onitsuka tiger': ['onitsuka', 'onitsuka tiger'],
  asics: ['asics'],
  reebok: ['reebok']
};

function normalized(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

export function brandConflict(input: SearchInput): string {
  const selected = normalized(input.brand);
  if (!selected) return '';
  const selectedBrand = Object.keys(brandAliases).find((brand) =>
    brandAliases[brand].some((alias) => selected === alias)
  );
  if (!selectedBrand) return '';
  const model = ` ${normalized(input.query)} `;
  const mentioned = Object.keys(brandAliases).find((brand) =>
    brand !== selectedBrand && brandAliases[brand].some((alias) => model.includes(` ${alias} `))
  );
  return mentioned ? `The model looks like ${mentioned}, but ${selectedBrand} is selected.` : '';
}

export function inputMatchesRequest(input: SearchInput, request: SearchResult['request']): boolean {
  const { allow_query_correction: _inputMode, ...inputBody } = createSearchBody(input);
  const { allow_query_correction: _requestMode, ...requestBody } = request;
  return JSON.stringify(inputBody) === JSON.stringify(requestBody);
}

export async function beginSearch(input: SearchInput, refreshId = '', allowQueryCorrection = true): Promise<{ id: string; cached: boolean }> {
  const response = await fetch(refreshId ? `/api/search/${refreshId}/refresh` : '/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: refreshId ? undefined : JSON.stringify(createSearchBody(input, allowQueryCorrection))
  });
  return apiJson(response, 'Could not start the search.');
}

export async function loadSearch(searchId: string): Promise<SearchResult> {
  const response = await fetch(`/api/search/${searchId}`);
  return apiJson(response, 'Could not load search results.');
}

export async function startRetailerSession(retailerId: string, searchId: string): Promise<{ viewer_url: string }> {
  const response = await fetch(`/api/retailers/${encodeURIComponent(retailerId)}/session/start`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_id: searchId })
  });
  return apiJson(response, 'Could not open the assisted retailer session.');
}

export async function completeRetailerSession(retailerId: string, searchId: string): Promise<{ id: string; cached: boolean }> {
  const response = await fetch(`/api/retailers/${encodeURIComponent(retailerId)}/session/complete`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_id: searchId, challenge_cleared: true })
  });
  return apiJson(response, 'Could not complete the assisted retailer session.');
}

export async function cancelRetailerSession(retailerId: string): Promise<void> {
  const response = await fetch(`/api/retailers/${encodeURIComponent(retailerId)}/session`, { method: 'DELETE' });
  await apiJson(response, 'Could not cancel the verification session.');
}

type EventSourceLike = {
  addEventListener(name: string, listener: (event: MessageEvent) => void): void;
  close(): void;
  onerror: ((event: Event) => void) | null;
};

export function connectSearchEvents(
  searchId: string,
  handlers: { update: () => void; complete: (result: SearchResult) => void; disconnect: () => void },
  createSource: (url: string) => EventSourceLike = (url) => new EventSource(url) as EventSourceLike
): EventSourceLike {
  const source = createSource(`/api/search/${searchId}/events`);
  for (const name of ['retailer_started', 'retailer_complete', 'retailer_error']) {
    source.addEventListener(name, handlers.update);
  }
  source.addEventListener('search_complete', (event) => {
    handlers.complete(JSON.parse((event as MessageEvent).data) as SearchResult);
    source.close();
  });
  source.onerror = () => {
    source.close();
    handlers.disconnect();
  };
  return source;
}
