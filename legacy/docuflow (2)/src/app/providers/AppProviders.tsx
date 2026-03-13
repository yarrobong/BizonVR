import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

interface AppProvidersProps {
  children: React.ReactNode;
}

const routerBasename = (import.meta.env.VITE_APP_BASENAME || '/').replace(/\/+$/, '') || '/';

export const AppProviders: React.FC<AppProvidersProps> = ({ children }) => (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter basename={routerBasename}>{children}</BrowserRouter>
  </QueryClientProvider>
);
