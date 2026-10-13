/** Display names/colours for stock ledger transaction types. */
export const TXN_LABELS: Record<string, { label: string; color: string }> = {
  OPENING: { label: 'Opening', color: 'blue' },
  PURCHASE_IN: { label: 'Purchase', color: 'green' },
  PURCHASE_RETURN_OUT: { label: 'Purchase return', color: 'volcano' },
  SALE_OUT: { label: 'Sale', color: 'red' },
  SALE_RETURN_IN: { label: 'Sales return', color: 'cyan' },
  TRANSFER_OUT: { label: 'Transfer out', color: 'orange' },
  TRANSFER_IN: { label: 'Transfer in', color: 'geekblue' },
  ADJUST_IN: { label: 'Adjustment +', color: 'green' },
  ADJUST_OUT: { label: 'Adjustment −', color: 'red' },
  COUNT_IN: { label: 'Count +', color: 'green' },
  COUNT_OUT: { label: 'Count −', color: 'red' },
};

export const STATUS_FILTER_OPTIONS = [
  { label: 'Draft', value: 'draft' },
  { label: 'Posted', value: 'posted' },
  { label: 'Cancelled', value: 'cancelled' },
];
