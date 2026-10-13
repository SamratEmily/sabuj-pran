import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import type { Page } from './client';

export const INVENTORY = {
  stock: '/inventory/stock',
  ledger: '/inventory/ledger',
  transfers: '/inventory/transfers',
  adjustments: '/inventory/adjustments',
  counts: '/inventory/counts',
} as const;

export type DocStatus = 'draft' | 'pending_approval' | 'posted' | 'cancelled' | 'rejected';

export interface StockRow {
  product_id: number;
  product_code: string;
  product_name: string;
  product_type: string;
  category_name: string;
  unit_code: string;
  warehouse_id: number;
  warehouse_name: string;
  qty_on_hand: string;
  qty_reserved: string;
  qty_available: string;
  avg_cost: string;
  value: string;
  reorder_level: string;
  is_low: boolean;
}

export interface StockPage extends Page<StockRow> {
  total_value: string;
}

export interface LedgerRow {
  id: number;
  txn_date: string;
  txn_type: string;
  warehouse_id: number;
  warehouse_name: string;
  qty_in: string;
  qty_out: string;
  unit_cost: string;
  balance_after: string;
  running_balance: string;
  ref_type: string;
  ref_id: number | null;
  note: string;
  reversal_of_id: number | null;
  created_by_name: string | null;
  created_at: string;
}

export interface LedgerPage extends Page<LedgerRow> {
  product_id: number;
  product_code: string;
  product_name: string;
  opening_balance: string;
  closing_balance: string;
}

interface DocItemBase {
  id: number;
  product_id: number;
  product_code: string;
  product_name: string;
  unit_code: string;
  unit_cost: string | null;
}

interface DocBase {
  id: number;
  number: string;
  status: DocStatus;
  note: string;
  created_by_name: string;
  posted_by_name: string | null;
  posted_at: string | null;
  created_at: string;
}

export interface TransferDoc extends DocBase {
  from_warehouse_id: number;
  from_warehouse_name: string;
  to_warehouse_id: number;
  to_warehouse_name: string;
  transfer_date: string;
  items: (DocItemBase & { qty: string })[];
}

export interface AdjustmentDoc extends DocBase {
  warehouse_id: number;
  warehouse_name: string;
  adjustment_date: string;
  reason: string;
  items: (DocItemBase & { direction: 'increase' | 'decrease'; qty: string; note: string })[];
}

export interface CountDoc extends DocBase {
  warehouse_id: number;
  warehouse_name: string;
  count_date: string;
  items: (DocItemBase & { system_qty: string; counted_qty: string; variance: string; current_qty: string | null })[];
  moved_since_snapshot?: number[];
}

export type StockDoc = TransferDoc | AdjustmentDoc | CountDoc;

/** Where a ledger row's reference document lives in the app (null = no page). */
export const REF_PATHS: Record<string, string> = {
  STOCK_TRANSFER: '/inventory/transfers',
  STOCK_ADJUSTMENT: '/inventory/adjustments',
  STOCK_COUNT: '/inventory/counts',
};

export const inventoryApi = {
  stock: (params: Record<string, unknown>) => api.get<StockPage>(INVENTORY.stock, { params }).then((r) => r.data),
  /** Every stock row of a warehouse (follows pagination). */
  allStockIn: async (warehouseId: number): Promise<StockRow[]> => {
    const rows: StockRow[] = [];
    for (let page = 1; ; page += 1) {
      const data = await inventoryApi.stock({ warehouse_id: warehouseId, page, page_size: 100 });
      rows.push(...data.items);
      if (rows.length >= data.total || data.items.length === 0) return rows;
    }
  },
  document: <T,>(endpoint: string, id: number) => api.get<T>(`${endpoint}/${id}`).then((r) => r.data),
  action: <T,>(endpoint: string, id: number, action: 'post' | 'cancel') =>
    api.post<T>(`${endpoint}/${id}/${action}`).then((r) => r.data),
};

/** On-hand / available of one product in one warehouse (null while unknown, zeros if never stocked). */
export function useStockOf(productId?: number | null, warehouseId?: number | null, enabled = true) {
  return useQuery({
    queryKey: [INVENTORY.stock, 'one', { product_id: productId, warehouse_id: warehouseId }],
    queryFn: async () => {
      const data = await inventoryApi.stock({ product_id: productId, warehouse_id: warehouseId, page_size: 1 });
      return data.items[0] ?? null;
    },
    enabled: enabled && !!productId && !!warehouseId,
    staleTime: 15_000,
  });
}
