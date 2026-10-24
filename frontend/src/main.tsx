import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@fontsource/pt-sans/400.css';
import '@fontsource/pt-sans/700.css';
import '@fontsource/pt-serif/400.css';
import '@fontsource/pt-serif/700.css';
import '@fontsource/pt-serif/400-italic.css';
import '@fontsource/pt-serif/700-italic.css';
import '@fontsource/pt-mono/400.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import './styles/ledger.css';
import { ApiError } from './api/client';
import { App } from './App';
import { theme } from './theme';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

async function start() {
  if (import.meta.env.VITE_API_MOCK === 'true') {
    try {
      const { startMocks } = await import('./mocks/browser');
      await startMocks();
    } catch (error) {
      console.error('[mock api] Имитация сервера не запустилась', error);
    }
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <MantineProvider theme={theme} defaultColorScheme="light">
        <Notifications position="bottom-center" limit={3} zIndex={400} />
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </MantineProvider>
    </StrictMode>,
  );
}

start();
