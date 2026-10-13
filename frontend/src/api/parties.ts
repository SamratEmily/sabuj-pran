import { api } from './client';

export type PartyKind = 'customers' | 'suppliers';

export const PARTY_ENDPOINT: Record<PartyKind, string> = {
  customers: '/customers',
  suppliers: '/suppliers',
};

export interface PartyRecord {
  id: number;
  code: string;
  name: string;
  contact_person: string;
  mobile: string;
  email: string;
  address: string;
  opening_due: string;
  notes: string;
  is_active: boolean;
  due: string;
  has_transactions: boolean;
  created_at: string;
}

export interface StatementEntry {
  id: number;
  entry_date: string;
  ref_type: string;
  ref_id: number | null;
  note: string;
  debit: string;
  credit: string;
  balance: string;
}

export interface Statement {
  party_type: 'customer' | 'supplier';
  party: { id: number; code: string; name: string; mobile: string; address: string };
  date_from: string | null;
  date_to: string | null;
  opening_balance: string;
  entries: StatementEntry[];
  total_debit: string;
  total_credit: string;
  closing_balance: string;
}

export const partiesApi = {
  statement: (kind: PartyKind, id: number, from?: string, to?: string) =>
    api
      .get<Statement>(`${PARTY_ENDPOINT[kind]}/${id}/statement`, { params: { from, to } })
      .then((r) => r.data),
};
