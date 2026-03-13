const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

const buildUrl = (path: string) => `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;

const parseError = async (response: Response) => {
  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    const data = await response.json().catch(() => null);
    const nestedMessage = String(data?.error?.message || '').trim();
    if (nestedMessage) {
      return nestedMessage;
    }

    const flatMessage = String(data?.error || '').trim();
    if (flatMessage) {
      return flatMessage;
    }
  }

  const text = await response.text().catch(() => '');
  if (!text && response.status >= 500) {
    return 'Backend API недоступен. Запустите сервер: `npm run start:server` или `npm run dev`.';
  }

  return text || `Request failed with status ${response.status}`;
};

export const requestJson = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
};

export const requestVoid = async (path: string, init?: RequestInit): Promise<void> => {
  const response = await fetch(buildUrl(path), init);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }
};

export const requestBlob = async (path: string, init?: RequestInit): Promise<Blob> => {
  const response = await fetch(buildUrl(path), init);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.blob();
};

export { buildUrl };
