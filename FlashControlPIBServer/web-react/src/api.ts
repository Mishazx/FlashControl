function csrfToken(): string {
  const item = document.cookie.split('; ').find((v) => v.startsWith('flashcontrol_csrf='));
  return item ? decodeURIComponent(item.split('=').slice(1).join('=')) : '';
}

export async function apiRequest<T = unknown>(
  path: string,
  { method = 'GET', params = {}, body, headers = {} }: {
    method?: string;
    params?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
    headers?: Record<string, string>;
  } = {},
): Promise<T> {
  const url = new URL('/api/v1' + path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) url.searchParams.set(key, String(value));
  });
  const requestHeaders: Record<string, string> = { Accept: 'application/json', ...headers };
  const options: RequestInit = { method, headers: requestHeaders, credentials: 'same-origin' };
  if (method !== 'GET') {
    requestHeaders['X-CSRF-Token'] = csrfToken();
  }
  if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
    options.body = typeof body === 'string' ? body : JSON.stringify(body);
  }
  const response = await fetch(url, options);
  if (response.status === 401) {
    throw new Error('401');
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      /* noop */
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function api<T = unknown>(path: string, params: Record<string, string | number | boolean | undefined | null> = {}): Promise<T> {
  return apiRequest<T>(path, { params });
}
