import { api } from './client';

export interface AdminUser {
  id: number;
  full_name: string;
  username: string;
  email: string | null;
  mobile: string | null;
  role_id: number;
  role_name: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface UserFormValues {
  full_name: string;
  username: string;
  email?: string | null;
  mobile?: string | null;
  role_id: number;
  password?: string;
  must_change_password?: boolean;
}

export interface RoleRecord {
  id: number;
  name: string;
  description: string;
  is_system: boolean;
  user_count: number;
  permission_count: number;
}

export interface PermissionGroup {
  module: string;
  permissions: { code: string; description: string }[];
}

export interface AuditLogRecord {
  id: number;
  user_id: number | null;
  user_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface CompanySettings {
  company_name: string;
  address: string;
  phone: string;
  email: string;
  currency_symbol: string;
  timezone: string;
  invoice_footer_note: string;
  logo_url: string;
  updated_at?: string;
}

export interface DocumentSequence {
  id: number;
  doc_type: string;
  label: string;
  prefix: string;
  padding: number;
  next_number: number;
  preview: string;
}

export const ADMIN = {
  users: '/admin/users',
  roles: '/admin/roles',
  permissions: '/admin/permissions',
  auditLogs: '/admin/audit-logs',
  companySettings: '/admin/company-settings',
  sequences: '/admin/document-sequences',
} as const;

export const adminApi = {
  resetUserPassword: (id: number, password: string) =>
    api.post<AdminUser>(`${ADMIN.users}/${id}/reset-password`, { password }).then((r) => r.data),
  permissionGroups: () => api.get<PermissionGroup[]>(ADMIN.permissions).then((r) => r.data),
  rolePermissions: (roleId: number) =>
    api.get<{ role_id: number; codes: string[] }>(`${ADMIN.roles}/${roleId}/permissions`).then((r) => r.data),
  setRolePermissions: (roleId: number, codes: string[]) =>
    api.put<{ role_id: number; codes: string[] }>(`${ADMIN.roles}/${roleId}/permissions`, { codes }).then((r) => r.data),
  deleteRole: (roleId: number) => api.delete(`${ADMIN.roles}/${roleId}`).then((r) => r.data),
  auditFacets: () =>
    api.get<{ entity_types: string[]; actions: string[] }>(`${ADMIN.auditLogs}/facets`).then((r) => r.data),
  companySettings: () => api.get<CompanySettings>(ADMIN.companySettings).then((r) => r.data),
  updateCompanySettings: (data: CompanySettings) =>
    api.put<CompanySettings>(ADMIN.companySettings, data).then((r) => r.data),
};
