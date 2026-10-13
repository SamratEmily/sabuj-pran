import { useQuery } from '@tanstack/react-query';

import { api } from './client';

export const MASTER = {
  categories: '/master/categories',
  units: '/master/units',
  products: '/master/products',
  prices: '/master/prices',
  warehouses: '/master/warehouses',
  expenseCategories: '/master/expense-categories',
  incomeCategories: '/master/income-categories',
  paymentMethods: '/master/payment-methods',
  lookups: '/master/lookups',
} as const;

export type ProductType = 'raw_material' | 'finished_good' | 'trading';
export type MethodType = 'cash' | 'bank' | 'mfs' | 'online';

export const PRODUCT_TYPE_LABELS: Record<ProductType, string> = {
  raw_material: 'Raw material',
  finished_good: 'Finished good',
  trading: 'Trading',
};
export const PRODUCT_TYPE_COLORS: Record<ProductType, string> = {
  raw_material: 'orange',
  finished_good: 'green',
  trading: 'blue',
};
export const METHOD_TYPE_LABELS: Record<MethodType, string> = {
  cash: 'Cash',
  bank: 'Bank',
  mfs: 'Mobile (MFS)',
  online: 'Online',
};

export interface Category {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
}

export interface UnitRecord {
  id: number;
  name: string;
  short_code: string;
  is_active: boolean;
}

export interface NamedRecord {
  id: number;
  name: string;
  is_active: boolean;
}

export interface PaymentMethodRecord {
  id: number;
  name: string;
  method_type: MethodType;
  is_active: boolean;
}

export interface WarehouseRecord {
  id: number;
  name: string;
  code: string;
  address: string;
  is_default: boolean;
  is_active: boolean;
}

export interface ProductRecord {
  id: number;
  code: string;
  name: string;
  category_id: number;
  category_name: string;
  unit_id: number;
  unit_name: string;
  unit_code: string;
  product_type: ProductType;
  purchase_price: string;
  reorder_level: string;
  description: string;
  is_active: boolean;
  current_price: string | null;
  price_effective_from: string | null;
}

export interface PriceRecord {
  id: number;
  product_id: number;
  price: string;
  effective_from: string;
  created_by: number;
  created_by_name: string | null;
  created_at: string;
  is_current: boolean;
}

export interface Lookups {
  categories: { id: number; name: string }[];
  units: { id: number; name: string; short_code: string }[];
  warehouses: { id: number; name: string; code: string; is_default: boolean }[];
  payment_methods: { id: number; name: string; method_type: MethodType }[];
  expense_categories: { id: number; name: string }[];
  income_categories: { id: number; name: string }[];
  money_accounts: { id: number; name: string; account_type: 'cash' | 'bank' | 'mfs' }[];
}

export const masterApi = {
  lookups: () => api.get<Lookups>(MASTER.lookups).then((r) => r.data),
  prices: (productId: number) =>
    api.get<PriceRecord[]>(`${MASTER.products}/${productId}/prices`).then((r) => r.data),
  addPrice: (productId: number, data: { price: string; effective_from?: string }) =>
    api.post<PriceRecord>(`${MASTER.products}/${productId}/prices`, data).then((r) => r.data),
};

/** Active reference data for dropdowns. Cached; refreshed whenever master data changes. */
export function useLookups() {
  return useQuery({ queryKey: [MASTER.lookups], queryFn: masterApi.lookups, staleTime: 5 * 60_000 });
}
