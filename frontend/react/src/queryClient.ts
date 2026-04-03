import { QueryClient } from "@tanstack/react-query";
import { persistQueryClient } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 24 * 60 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

let persistenceConfigured = false;

export function setupQueryPersistence() {
  if (persistenceConfigured || typeof window === "undefined") {
    return;
  }

  const persister = createSyncStoragePersister({
    storage: window.localStorage,
    key: "deltaconverge-query-cache-v2",
  });

  persistQueryClient({
    queryClient,
    persister,
    maxAge: 24 * 60 * 60 * 1000,
  });

  persistenceConfigured = true;
}
