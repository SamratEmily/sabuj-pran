import { api } from './client';

export const PURCHASE = {
  orders: '/purchase/orders',
  direct: '/purchase/direct',
  receipts: '/purchase/receipts',
  returns: '/purchase/returns',
} as const;

export type PoStatus = 'draft' | 'pending_approval' | 'approved' | 'partially_received' | 'received' | 'cancelled' | 'rejected';

interface Line {
  id: number;
  product_id: number;
  product_code: string;
  product_name: string;
  unit_code: string;
}

export interface PoItem extends Line {
  qty: string;
  unit_cost: string;
  line_total: string;
  received_qty: string;
  remaining_qty: string;
}

export interface ReturnItem extends Line {
  grn_item_id: number;
  qty: string;
  unit_cost: string;
  line_total: string;
}

export interface PurchaseReturnDoc {
  id: number;
  prn_number: string;
  goods_receipt_id: number;
  grn_number: string;
  po_id: number | null;
  po_number: string | null;
  supplier_id: number;
  supplier_name: string;
  warehouse_id: number;
  warehouse_name: string;
  return_date: string;
  subtotal: string;
  discount: string;
  total: string;
  notes: string;
  created_by_name: string;
  created_at: string;
  items: ReturnItem[];
}

export interface ReceiptItem extends Line {
  po_item_id: number | null;
  qty: string;
  unit_cost: string;
  line_total: string;
  returned_qty: string;
  returnable_qty: string;
}

export interface GoodsReceiptDoc {
  id: number;
  grn_number: string;
  po_id: number | null;
  po_number: string | null;
  supplier_id: number;
  supplier_name: string;
  warehouse_id: number;
  warehouse_name: string;
  receipt_date: string;
  subtotal: string;
  discount: string;
  total: string;
  is_direct: boolean;
  notes: string;
  created_by_name: string;
  created_at: string;
  items: ReceiptItem[];
  returns: PurchaseReturnDoc[];
}

export interface PurchaseOrder {
  id: number;
  po_number: string;
  supplier_id: number;
  supplier_code: string;
  supplier_name: string;
  warehouse_id: number;
  warehouse_name: string;
  order_date: string;
  expected_date: string | null;
  status: PoStatus;
  subtotal: string;
  discount: string;
  total: string;
  notes: string;
  created_by_name: string;
  approved_by_name: string | null;
  approved_at: string | null;
  created_at: string;
  items: PoItem[];
}

export interface PurchaseOrderDetail extends PurchaseOrder {
  receipts: GoodsReceiptDoc[];
  supplier_due: string;
}

export interface PoPayload {
  supplier_id: number;
  warehouse_id: number;
  order_date?: string;
  expected_date?: string | null;
  discount: string;
  notes: string;
  items: { product_id: number; qty: string; unit_cost: string }[];
}

export const purchaseApi = {
  order: (id: number) => api.get<PurchaseOrderDetail>(`${PURCHASE.orders}/${id}`).then((r) => r.data),
  direct: (data: PoPayload) => api.post<PurchaseOrderDetail>(PURCHASE.direct, data).then((r) => r.data),
  action: (id: number, action: 'approve' | 'cancel') =>
    api.post<PurchaseOrderDetail>(`${PURCHASE.orders}/${id}/${action}`).then((r) => r.data),
  receive: (id: number, data: { receipt_date?: string; notes: string; items: { po_item_id: number; qty: string; unit_cost?: string }[] }) =>
    api.post<GoodsReceiptDoc>(`${PURCHASE.orders}/${id}/receive`, data).then((r) => r.data),
  returnGoods: (grnId: number, data: { return_date?: string; notes: string; items: { grn_item_id: number; qty: string }[] }) =>
    api.post<PurchaseReturnDoc>(`${PURCHASE.receipts}/${grnId}/return`, data).then((r) => r.data),
};
