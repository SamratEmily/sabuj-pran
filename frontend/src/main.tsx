import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import axios from 'axios';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';

import NotificationBridge from './components/NotificationBridge';
import { AuthProvider } from './hooks/useAuth';
import { router } from './routes';
import { notifyError } from './utils/notify';
import './styles/print.css';

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: {
      /** The caller shows the error itself (inline alert / form fields). */
      silent?: boolean;
    };
  }
}

const queryClient = new QueryClient({
  // Failed first loads are shown by each page's error state; only background refetch
  // failures (page already has data) need a notification.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.state.data !== undefined) notifyError(error, 'Could not refresh data');
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _result, mutation) => {
      if (!mutation.meta?.silent) notifyError(error);
    },
  }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Retry network/5xx once; 4xx answers won't change on retry.
      retry: (count, error) => count < 1 && !(axios.isAxiosError(error) && (error.response?.status ?? 500) < 500),
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider>
      <AntApp>
        <NotificationBridge />
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
