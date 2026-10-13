import { api } from './client';

export const SALES = {
  quotations: '/sales/quotations',
  orders: '/sales/orders',
  deliveries: '/sales/deliveries',
  invoices: '/sales/invoices',
  returns: '/sales/returns',
} as const;

export type QuotationStatus = 'draft' | 'sent' | 'accepted' | 'rejected' | 'converted';
export type SoStatus = 'draft' | 'confirmed' | 'partially_delivered' | 'delivered' | 'cancelled';
export type InvoiceStatus = 'unpaid' | 'partial' | 'paid';

interface Line {
  id: number;
  product_id: number;
  product_code: string;
  product_name: string;
  unit_code: string;
}

interface CustomerRef {
  customer_id: number;
  customer_code: string;
  customer_name: string;
}

export interface QuotationItem extends Line {
  qty: string;
  unit_price: string;
  line_total: string;
}

export interface Quotation extends CustomerRef {
  id: number;
  qt_number: string;
  quote_date: string;
  valid_until: string | null;
  status: QuotationStatus;
  subtotal: string;
  discount: string;
  total: string;
  notes: string;
  converted_order_id: number | null;
  converted_order_number: string | null;
  created_by_name: string;
  created_at: string;
  items: QuotationItem[];
}

export interface SoItem extends Line {
  qty_ordered: string;
  unit_price: string;
  line_total: string;
  qty_reserved: string;
  qty_produced: string;
  qty_delivered: string;
  qty_remaining: string;
  qty_available: string | null;
}

export interface SalesOrder extends CustomerRef {
  id: number;
  so_number: string;
  quotation_id: number | null;
  quotation_number: string | null;
  warehouse_id: number;
  warehouse_name: string;
  order_date: string;
  delivery_date: string | null;
  status: SoStatus;
  subtotal: string;
  discount: string;
  total: string;
  notes: string;
  created_by_name: string;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
  created_at: string;
  items: SoItem[];
}

export interface DeliveryItem extends Line {
  so_item_id: number;
  qty: string;
  unit_price: string;
  unit_cost_cogs: string;
}

export interface DeliveryDoc extends CustomerRef {
  id: number;
  dlv_number: string;
  sales_order_id: number;
  so_number: string;
  warehouse_id: number;
  warehouse_name: string;
  delivery_date: string;
  invoice_id: number | null;
  inv_number: string | null;
  notes: string;
  created_by_name: string;
  created_at: string;
  items: DeliveryItem[];
}

export interface InvoiceItem extends Line {
  delivery_item_id: number;
  qty: string;
  unit_price: string;
  unit_cost: string;
  line_total: string;
  qty_returned: string;
  qty_returnable: string;
}

export interface Invoice extends CustomerRef {
  id: number;
  inv_number: string;
  sales_order_id: number;
  so_number: string;
  delivery_id: number;
  dlv_number: string;
  warehouse_id: number;
  warehouse_name: string;
  invoice_date: string;
  subtotal: string;
  discount: string;
  total: string;
  paid_amount: string;
  returned_amount: string;
  refunded_amount: string;
  outstanding: string;
  status: InvoiceStatus;
  cogs_total: string;
  created_by_name: string;
  created_at: string;
  items: InvoiceItem[];
}

export interface SoDetail extends SalesOrder {
  customer_due: string;
  deliveries: DeliveryDoc[];
  invoices: Invoice[];
}

export interface ReserveLine {
  so_item_id: number;
  product_code: string;
  product_name: string;
  wanted: string;
  reserved_now: string;
  reserved_total: string;
  short: string;
}

export interface SalesReturnItem extends Line {
  invoice_item_id: number;
  qty: string;
  unit_price: string;
  unit_cost: string;
  line_total: string;
}

export interface SalesReturnDoc extends CustomerRef {
  id: number;
  srn_number: string;
  invoice_id: number;
  inv_number: string;
  warehouse_id: number;
  warehouse_name: string;
  return_date: string;
  subtotal: string;
  discount: string;
  total: string;
  refund_amount: string;
  refund_account_id: number | null;
  refund_account_name: string | null;
  notes: string;
  created_by_name: string;
  created_at: string;
  items: SalesReturnItem[];
}

export interface InvoiceDetail extends Invoice {
  customer_due: string;
  customer_mobile: string;
  customer_address: string;
  returns: SalesReturnDoc[];
  collections: { id: number; number: string; collection_date: string; amount: string; status: string; account_name: string }[];
  company: {
    company_name: string;
    address: string;
    phone: string;
    email: string;
    currency_symbol: string;
    invoice_footer_note: string;
    logo_url: string;
  };
}

export interface LinesPayload {
  customer_id: number;
  discount: string;
  notes: string;
  items: { product_id: number; qty: string; unit_price: string }[];
}

export interface DeliverPayload {
  delivery_date?: string;
  create_invoice: boolean;
  notes: string;
  items: { so_item_id: number; qty: string }[];
}

export interface ReturnPayload {
  return_date?: string;
  refund_amount: string;
  refund_account_id: number | null;
  notes: string;
  items: { invoice_item_id: number; qty: string }[];
}

export const salesApi = {
  quotationAction: (id: number, action: 'send' | 'accept' | 'reject') =>
    api.post<Quotation>(`${SALES.quotations}/${id}/${action}`).then((r) => r.data),
  convert: (id: number, warehouseId?: number) =>
    api.post<SoDetail>(`${SALES.quotations}/${id}/convert`, { warehouse_id: warehouseId ?? null }).then((r) => r.data),
  order: (id: number) => api.get<SoDetail>(`${SALES.orders}/${id}`).then((r) => r.data),
  orderAction: (id: number, action: 'confirm' | 'cancel' | 'release') =>
    api.post<SoDetail>(`${SALES.orders}/${id}/${action}`).then((r) => r.data),
  reserve: (id: number) =>
    api.post<{ order: SoDetail; lines: ReserveLine[] }>(`${SALES.orders}/${id}/reserve`, {}).then((r) => r.data),
  setProduced: (id: number, itemId: number, qty: string) =>
    api.put<SoDetail>(`${SALES.orders}/${id}/items/${itemId}/produced`, { qty_produced: qty }).then((r) => r.data),
  deliver: (id: number, data: DeliverPayload) => api.post<DeliveryDoc>(`${SALES.orders}/${id}/deliver`, data).then((r) => r.data),
  invoiceDelivery: (dlvId: number) => api.post<InvoiceDetail>(`${SALES.deliveries}/${dlvId}/invoice`).then((r) => r.data),
  invoice: (id: number) => api.get<InvoiceDetail>(`${SALES.invoices}/${id}`).then((r) => r.data),
  returnGoods: (invoiceId: number, data: ReturnPayload) =>
    api.post<SalesReturnDoc>(`${SALES.invoices}/${invoiceId}/return`, data).then((r) => r.data),
};

/** Query keys refreshed after any sales posting (stock, dues, money). */
export const SALES_INVALIDATES = [
  SALES.quotations,
  SALES.orders,
  SALES.deliveries,
  SALES.invoices,
  SALES.returns,
  '/inventory/stock',
  '/customers',
  '/money/accounts',
  '/money/collections',
] as const;
