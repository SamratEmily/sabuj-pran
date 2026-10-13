import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { authApi } from '../api/auth';
import type { AuthUser } from '../api/auth';
import { setUnauthorizedHandler, tokenStorage } from '../api/client';

export const ME_QUERY_KEY = ['auth', 'me'] as const;

interface AuthContextValue {
  user: AuthUser | null;
  permissions: ReadonlySet<string>;
  /** True while a stored token is being exchanged for the user profile. */
  isRestoring: boolean;
  /** Set when the stored session could not be loaded for a reason other than 401. */
  sessionError: unknown;
  retrySession: () => void;
  login: (identifier: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  setUser: (user: AuthUser) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const NO_PERMISSIONS: ReadonlySet<string> = new Set();

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(() => tokenStorage.get());

  const me = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: authApi.me,
    enabled: token !== null,
    staleTime: Infinity,
    retry: false,
  });

  const clearSession = useCallback(() => {
    tokenStorage.clear();
    setToken(null);
    queryClient.clear();
  }, [queryClient]);

  // Any 401 from the API (expired token, deactivated user) ends the session.
  useEffect(() => setUnauthorizedHandler(clearSession), [clearSession]);

  const login = useCallback(
    async (identifier: string, password: string) => {
      const res = await authApi.login(identifier, password);
      tokenStorage.set(res.access_token);
      queryClient.setQueryData(ME_QUERY_KEY, res.user);
      setToken(res.access_token);
      return res.user;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout(); // audit only; the token is stateless
    } catch {
      // ignore: we log out locally either way
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const setUser = useCallback(
    (user: AuthUser) => queryClient.setQueryData(ME_QUERY_KEY, user),
    [queryClient],
  );

  const user = token !== null ? (me.data ?? null) : null;
  const permissions = useMemo(
    () => (user ? new Set(user.permissions) : NO_PERMISSIONS),
    [user],
  );

  const value: AuthContextValue = {
    user,
    permissions,
    isRestoring: token !== null && me.isPending,
    sessionError: token !== null ? me.error : null,
    retrySession: () => void me.refetch(),
    login,
    logout,
    setUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
