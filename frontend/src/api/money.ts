import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { Page } from './client';

export const MONEY = {
  accounts: '/money/accounts',
  position: '/money/position',
  collections: '/money/collections',
  supplierPayments: '/money/supplier-payments',
  expenses: '/money/expenses',
  incomes: '/money/incomes',
  transfers: '/money/transfers',
} as const;

export type AccountType = 'cash' | 'bank' | 'mfs';
export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = { cash: 'Cash', bank: 'Bank', mfs: 'Mobile (MFS)' };
export const ACCOUNT_TYPE_COLORS: Record<AccountType, string> = { cash: 'green', bank: 'blue', mfs: 'magenta' };

export interface MoneyAccountRecord {
  id: number;
  name: string;
  account_type: AccountType;
  payment_method_id: number | null;
  payment_method_name: string | null;
  account_number: string;
  opening_balance: string;
  balance: string;
  is_active: boolean;
  has_transactions: boolean;
}

export interface Position {
  cash: string;
  bank: string;
  mfs: string;
  total: string;
}

export interface AccountLedgerRow {
  id: number;
  txn_date: string;
  txn_type: string;
  direction: 'in' | 'out';
  amount: string;
  money_in: string;
  money_out: string;
  balance_after: string;
  running_balance: string;
  ref_type: string;
  ref_id: number | null;
  note: string;
  reversal_of_id: number | null;
  created_by_name: string | null;
  created_at: string;
}

export interface AccountLedgerPage extends Page<AccountLedgerRow> {
  account_id: number;
  account_name: string;
  opening_balance: string;
  closing_balance: string;
}

export interface VoucherRecord {
  id: number;
  number: string;
  voucher_date: string;
  amount: string;
  status: 'draft' | 'pending_approval' | 'posted' | 'reversed' | 'rejected';
  account_id: number | null;
  account_name: string | null;
  party_id?: number | null;
  party_code?: string | null;
  party_name?: string | null;
  party_due?: string | null;
  reference_no?: string | null;
  invoice_id?: number | null;
  invoice_number?: string | null;
  category_id?: number | null;
  category_name?: string | null;
  paid_to?: string | null;
  from_account_id?: number | null;
  from_account_name?: string | null;
  to_account_id?: number | null;
  to_account_name?: string | null;
  notes: string;
  created_by_name: string;
  created_at: string;
  reversed_by_name: string | null;
  reversed_at: string | null;
  reversal_reason: string;
}

export const moneyApi = {
  position: () => api.get<Position>(MONEY.position).then((r) => r.data),
  account: (id: number) => api.get<MoneyAccountRecord>(`${MONEY.accounts}/${id}`).then((r) => r.data),
  reverse: (endpoint: string, id: number, reason: string) =>
    api.post<VoucherRecord>(`${endpoint}/${id}/reverse`, { reason }).then((r) => r.data),
};

/** Current balance of one account (only for users who may view accounts). */
export function useAccountBalance(id?: number | null, enabled = true) {
  return useQuery({
    queryKey: [MONEY.accounts, 'detail', id],
    queryFn: () => moneyApi.account(id!),
    enabled: enabled && !!id,
  });
}
