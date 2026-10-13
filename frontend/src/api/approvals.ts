import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { Page } from './client';

export const APPROVALS = {
  rules: '/approvals/rules',
  pending: '/approvals/pending',
  pendingCount: '/approvals/pending/count',
  history: '/approvals/history',
} as const;

export type DocumentType = 'PURCHASE_ORDER' | 'EXPENSE' | 'SUPPLIER_PAYMENT' | 'STOCK_ADJUSTMENT';

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  PURCHASE_ORDER: 'Purchase order',
  EXPENSE: 'Expense',
  SUPPLIER_PAYMENT: 'Supplier payment',
  STOCK_ADJUSTMENT: 'Stock adjustment',
};

export const DOCUMENT_TYPE_OPTIONS = (Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[]).map((value) => ({
  value,
  label: DOCUMENT_TYPE_LABELS[value],
}));

export interface ApprovalRule {
  id: number;
  document_type: DocumentType;
  document_label: string;
  min_amount: string;
  approver_role_id: number;
  approver_role_name: string;
  is_active: boolean;
}

export interface ApprovalRequest {
  id: number;
  document_type: DocumentType;
  document_label: string;
  document_id: number;
  document_number: string;
  amount: string;
  status: 'pending' | 'approved' | 'rejected';
  approver_role_id: number;
  approver_role_name: string;
  requested_by: number;
  requested_by_name: string;
  requested_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  remark: string;
  can_decide: boolean;
}

/** Where each approvable document lives in the app. */
export function documentLink(a: Pick<ApprovalRequest, 'document_type' | 'document_id' | 'document_number'>): string {
  switch (a.document_type) {
    case 'PURCHASE_ORDER':
      return `/purchase/orders/${a.document_id}`;
    case 'STOCK_ADJUSTMENT':
      return `/inventory/adjustments/${a.document_id}`;
    case 'EXPENSE':
      return `/money/expenses?search=${encodeURIComponent(a.document_number)}`;
    case 'SUPPLIER_PAYMENT':
      return `/money/supplier-payments?search=${encodeURIComponent(a.document_number)}`;
  }
}

export const approvalsApi = {
  decide: (id: number, decision: 'approve' | 'reject', remark: string) =>
    api.post<ApprovalRequest>(`/approvals/${id}/${decision}`, { remark }).then((r) => r.data),
  latestFor: (documentType: DocumentType, number: string) =>
    api
      .get<Page<ApprovalRequest>>(APPROVALS.history, { params: { document_type: documentType, search: number, page_size: 1 } })
      .then((r) => r.data.items[0] ?? null),
};

/** Requests waiting for the current user's decision (menu badge). */
export function usePendingCount(enabled: boolean) {
  return useQuery({
    queryKey: [APPROVALS.pendingCount],
    queryFn: () => api.get<{ count: number }>(APPROVALS.pendingCount).then((r) => r.data.count),
    enabled,
    refetchInterval: 60_000,
  });
}
