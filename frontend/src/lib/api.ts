export async function apiJson<T>(response: Response, fallback: string): Promise<T> {
  const isJson = response.headers.get('content-type')?.toLowerCase().includes('application/json');
  let payload: unknown = null;

  if (isJson) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : null;
    throw new Error(typeof detail === 'string' ? detail : `${fallback} (HTTP ${response.status})`);
  }
  if (payload === null) {
    throw new Error(`${fallback} The server returned an unexpected response.`);
  }
  return payload as T;
}
