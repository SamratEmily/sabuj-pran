import { useQuery } from '@tanstack/react-query';

import { api } from './client';

export const DASHBOARD = { summary: '/dashboard/summary' } as const;

export interface PartyDue {
  id: number;
  code: string;
  name: string;
  due: string;
}

export interface LowStockRow {
  product_id: number;
  product_code: string;
  product_name: string;
  warehouse_name: string;
  qty_on_hand: string;
  reorder_level: string;
}

export interface SeriesPoint {
  date: string;
  sales?: string | null;
  collection?: string | null;
}

/** Every metric is optional: the API leaves out sections the user may not see. */
export interface DashboardSummary {
  as_of: string;
  month_start: string;
  generated_at: string;
  sections: string[];
  today_sales?: string;
  today_collection?: string;
  today_expenses?: string;
  today_purchase?: string;
  cash_balance?: string;
  bank_balance?: string;
  mfs_balance?: string;
  customer_due?: string;
  supplier_due?: string;
  inventory_value?: string;
  pending_orders_count?: number;
  pending_orders_value?: string;
  estimated_profit_mtd?: string;
  top_customers?: PartyDue[];
  top_suppliers?: PartyDue[];
  low_stock?: LowStockRow[];
  sales_vs_collection?: SeriesPoint[];
}

export function useDashboard() {
  return useQuery({
    queryKey: [DASHBOARD.summary],
    queryFn: () => api.get<DashboardSummary>(DASHBOARD.summary).then((r) => r.data),
    refetchInterval: 60_000,
  });
}
