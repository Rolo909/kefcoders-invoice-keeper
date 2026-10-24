import { getResponse } from 'msw';
import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';
import { reset } from './db';

function interceptFetch() {
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input instanceof Request ? input : new URL(String(input), window.location.href), init);
    if (new URL(request.url).pathname.startsWith('/api/')) {
      const response = await getResponse(handlers, request);
      if (response) return response;
    }
    return original(input, init);
  };
}

export async function startMocks() {
  const url = new URL(window.location.href);
  if (url.searchParams.has('reset-demo')) {
    reset();
    try {
      localStorage.removeItem('ik-mock-session');
    } catch {
      // storage unavailable
    }
    url.searchParams.delete('reset-demo');
    window.history.replaceState(null, '', url.toString());
  }
  if ('serviceWorker' in navigator) {
    try {
      await setupWorker(...handlers).start({ onUnhandledRequest: 'bypass', quiet: true });
      return;
    } catch (error) {
      console.warn('[mock api] Service Worker недоступен, перехватываю fetch напрямую', error);
    }
  }
  interceptFetch();
}
