import { useAuth } from './useAuth';

/** A permission code, or a list meaning "any of these". */
export type PermissionRule = string | readonly string[];

export function hasPermission(permissions: ReadonlySet<string>, rule?: PermissionRule): boolean {
  if (!rule) return true;
  return typeof rule === 'string' ? permissions.has(rule) : rule.some((c) => permissions.has(c));
}

/** `usePermission("product.create")` or `usePermission(["a.view", "b.view"])` (any of). */
export function usePermission(rule?: PermissionRule): boolean {
  return hasPermission(useAuth().permissions, rule);
}
