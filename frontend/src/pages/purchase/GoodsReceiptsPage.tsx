import { Input, Tabs, Tag, Typography } from 'antd';
import type { TableProps } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { PURCHASE } from '../../api/purchase';
import type { GoodsReceiptDoc, PurchaseReturnDoc } from '../../api/purchase';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import PagedTable from '../../components/PagedTable';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { formatDecimal } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;
const poLink = (id: number | null, number: string | null) =>
  id ? <Link to={`${PURCHASE.orders}/${id}`}>{number}</Link> : '—';

function DocTable<T extends { id: number }>({ endpoint, columns, placeholder, empty }: {
  endpoint: string;
  columns: TableProps<T>['columns'];
  placeholder: string;
  empty: string;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState<string>();
  const list = useList<T>(endpoint, { page, page_size: pageSize, search });
  return (
    <>
      <Input.Search
        allowClear
        placeholder={placeholder}
        style={{ width: 260, marginBottom: 16 }}
        onSearch={(v) => {
          setSearch(v.trim() || undefined);
          setPage(1);
        }}
      />
      <PagedTable<T>
        query={list}
        columns={columns}
        page={page}
        pageSize={pageSize}
        onPageChange={(p, ps) => {
          setPage(p);
          setPageSize(ps);
        }}
        emptyText={empty}
      />
    </>
  );
}

const receiptColumns: TableProps<GoodsReceiptDoc>['columns'] = [
  { title: 'GRN', dataIndex: 'grn_number', render: (v: string, g) => <>{<strong>{v}</strong>} {g.is_direct && <Tag color="purple">Direct</Tag>}</> },
  { title: 'Date', dataIndex: 'receipt_date', render: (v: string) => <DateText value={v} /> },
  { title: 'Purchase order', key: 'po', render: (_, g) => poLink(g.po_id, g.po_number) },
  { title: 'Supplier', dataIndex: 'supplier_name' },
  { title: 'Warehouse', dataIndex: 'warehouse_name' },
  { title: right('Lines'), key: 'n', render: (_, g) => right(String(g.items.length)) },
  { title: right('Credited'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
  { title: 'Returns', key: 'r', render: (_, g) => (g.returns.length ? g.returns.map((r) => r.prn_number).join(', ') : <Typography.Text type="secondary">—</Typography.Text>) },
];

const returnColumns: TableProps<PurchaseReturnDoc>['columns'] = [
  { title: 'PRN', dataIndex: 'prn_number', render: (v: string) => <strong>{v}</strong> },
  { title: 'Date', dataIndex: 'return_date', render: (v: string) => <DateText value={v} /> },
  { title: 'Receipt', dataIndex: 'grn_number' },
  { title: 'Purchase order', key: 'po', render: (_, r) => poLink(r.po_id, r.po_number) },
  { title: 'Supplier', dataIndex: 'supplier_name' },
  { title: 'Items', key: 'i', render: (_, r) => r.items.map((i) => `${formatDecimal(i.qty, 3, true)} ${i.unit_code} ${i.product_code}`).join(', ') },
  { title: right('Debited'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
  { title: 'Notes', dataIndex: 'notes', ellipsis: true },
];

export default function GoodsReceiptsPage() {
  const canReceipts = usePermission('goods_receipt.view');
  const canReturns = usePermission('purchase_return.view');
  return (
    <>
      <PageHeader title="Goods Receipts & Returns" subtitle="Receive and return goods from a purchase order's page." />
      <Tabs
        items={[
          ...(canReceipts
            ? [{ key: 'receipts', label: 'Goods receipts', children: <DocTable<GoodsReceiptDoc> endpoint={PURCHASE.receipts} columns={receiptColumns} placeholder="Search GRN number" empty="No goods received yet" /> }]
            : []),
          ...(canReturns
            ? [{ key: 'returns', label: 'Purchase returns', children: <DocTable<PurchaseReturnDoc> endpoint={PURCHASE.returns} columns={returnColumns} placeholder="Search PRN number" empty="No purchase returns yet" /> }]
            : []),
        ]}
      />
    </>
  );
}
