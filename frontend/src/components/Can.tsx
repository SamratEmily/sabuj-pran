import type { ReactNode } from 'react';

import { usePermission } from '../hooks/usePermission';
import type { PermissionRule } from '../hooks/usePermission';

interface Props {
  /** A code, or a list meaning "any of these". */
  permission: PermissionRule;
  children: ReactNode;
  fallback?: ReactNode;
}

/** Renders children only if the user has the permission. The backend still enforces it. */
export default function Can({ permission, children, fallback = null }: Props) {
  return <>{usePermission(permission) ? children : fallback}</>;
}
