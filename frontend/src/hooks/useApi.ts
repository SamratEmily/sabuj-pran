import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Page } from '../api/client';

export type ListParams = Record<string, string | number | boolean | null | undefined>;

function cleanParams(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  );
}

/** Paginated list from a standard list endpoint. Query key: [endpoint, params]. */
export function useList<T>(endpoint: string, params: ListParams = {}, enabled = true) {
  const query = cleanParams(params);
  return useQuery({
    queryKey: [endpoint, query],
    queryFn: () => api.get<Page<T>>(endpoint, { params: query }).then((r) => r.data),
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Single record: GET `${endpoint}/${id}`. */
export interface SaveVariables<TIn> {
  id?: number | string;
  data: TIn;
}

interface MutationOpts {
  /** Skip the global error notification (the caller shows errors itself). */
  silent?: boolean;
  /** Other query-key prefixes to refresh on success (e.g. a lookups endpoint). */
  invalidates?: readonly string[];
}

function useInvalidate(endpoint: string, extra: readonly string[] = []) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([endpoint, ...extra].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
}

/** Create (POST endpoint) or update (PUT endpoint/id). Invalidates every query under `endpoint`. */
export function useSave<TIn, TOut = unknown>(endpoint: string, opts: MutationOpts = {}) {
  const invalidate = useInvalidate(endpoint, opts.invalidates);
  return useMutation({
    mutationFn: ({ id, data }: SaveVariables<TIn>) =>
      (id === undefined
        ? api.post<TOut>(endpoint, data)
        : api.put<TOut>(`${endpoint}/${id}`, data)
      ).then((r) => r.data),
    onSuccess: invalidate,
    meta: { silent: opts.silent },
  });
}

export type RecordActionVariables = number | string | { id: number | string; params?: ListParams };

/** POST `${endpoint}/${id}/${action}` (e.g. deactivate, activate, post, cancel). */
export function useRecordAction<TOut = unknown>(endpoint: string, action: string, opts: MutationOpts = {}) {
  const invalidate = useInvalidate(endpoint, opts.invalidates);
  return useMutation({
    mutationFn: (vars: RecordActionVariables) => {
      const { id, params } = typeof vars === 'object' ? vars : { id: vars, params: undefined };
      return api.post<TOut>(`${endpoint}/${id}/${action}`, undefined, { params }).then((r) => r.data);
    },
    onSuccess: invalidate,
    meta: { silent: opts.silent },
  });
}
