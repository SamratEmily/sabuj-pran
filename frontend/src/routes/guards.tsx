import { Button, Flex, Result, Spin } from 'antd';
import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router';

import { errorMessage } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { usePermission } from '../hooks/usePermission';
import type { PermissionRule } from '../hooks/usePermission';

export const CHANGE_PASSWORD_PATH = '/profile/password';

/** Only for logged-in users. Sends users flagged must_change_password to change it first. */
export function ProtectedRoute() {
  const { user, isRestoring, sessionError, retrySession, logout } = useAuth();
  const location = useLocation();

  if (isRestoring) {
    return (
      <Flex justify="center" align="center" style={{ minHeight: '100vh' }}>
        <Spin size="large" />
      </Flex>
    );
  }
  if (!user && sessionError) {
    return (
      <Result
        status="warning"
        title="Could not load your session"
        subTitle={errorMessage(sessionError)}
        extra={[
          <Button key="retry" type="primary" onClick={retrySession}>
            Retry
          </Button>,
          <Button key="logout" onClick={() => void logout()}>
            Log out
          </Button>,
        ]}
      />
    );
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (user.must_change_password && location.pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }
  return <Outlet />;
}

/**
 * Login page: once a user is set (already logged in, or just logged in), go to the page
 * they originally asked for. This is also how LoginPage redirects after success.
 */
export function GuestOnlyRoute({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  return user ? <Navigate to={from && from !== '/login' ? from : '/'} replace /> : <>{children}</>;
}

/** Page-level permission guard (the menu hides the link, this blocks typed URLs). */
export function RequirePermission({ permission, children }: { permission?: PermissionRule; children: ReactNode }) {
  const allowed = usePermission(permission);
  if (!allowed) {
    return <Result status="403" title="No access" subTitle="You do not have permission to open this page." />;
  }
  return <>{children}</>;
}
