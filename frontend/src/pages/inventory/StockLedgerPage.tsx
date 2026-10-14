import { DatePicker, Empty, Flex, Select, Table, Tag, Typography } from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import { Link, useSearchParams } from 'react-router';

import { INVENTORY, REF_PATHS } from '../../api/inventory';
import type { LedgerPage, LedgerRow } from '../../api/inventory';
import { useLookups } from '../../api/master';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import PagedTable from '../../components/PagedTable';
import ProductSelect from '../../components/ProductSelect';
import QtyText from '../../components/QtyText';
import { useList } from '../../hooks/useApi';
import { TXN_LABELS } from './labels';
import { compare } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

type Row = LedgerRow & { kind?: 'opening' };

export default function StockLedgerPage() {
  const lookups = useLookups();
  // Filters live in the URL so Current Stock can deep-link here and the view can be shared.
  const [params, setParams] = useSearchParams();
  const productId = Number(params.get('product_id')) || undefined;
  const warehouseId = Number(params.get('warehouse_id')) || undefined;
  const from = params.get('from') ?? undefined;
  const to = params.get('to') ?? undefined;
  const page = Number(params.get('page')) || 1;
  const pageSize = Number(params.get('page_size')) || 50;

  const set = (patch: Record<string, string | number | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === '') next.delete(k);
      else next.set(k, String(v));
    }
    if (!('page' in patch)) next.delete('page');
    setParams(next, { replace: true });
  };

  const ledger = useList<LedgerRow>(
    INVENTORY.ledger,
    { product_id: productId, warehouse_id: warehouseId, from, to, page, page_size: pageSize },
    !!productId,
  );
  const data = ledger.data as LedgerPage | undefined;

  const rows: Row[] =
    data && page === 1
      ? [
          {
            id: 0,
            kind: 'opening',
            txn_date: from ?? '',
            txn_type: '',
            warehouse_id: 0,
            warehouse_name: '',
            qty_in: '',
            qty_out: '',
            unit_cost: '',
            balance_after: '',
            running_balance: data.opening_balance,
            ref_type: '',
            ref_id: null,
            note: 'Opening balance',
            reversal_of_id: null,
            created_by_name: null,
            created_at: '',
          },
          ...data.items,
        ]
      : (data?.items ?? []);

  const columns: TableProps<Row>['columns'] = [
    { title: 'Date', dataIndex: 'txn_date', width: 120, render: (v: string, r) => (r.kind ? (v ? <DateText value={v} /> : '—') : <DateText value={v} />) },
    {
      title: 'Type',
      dataIndex: 'txn_type',
      render: (t: string, r) =>
        r.kind ? <Typography.Text italic>Opening balance</Typography.Text> : <Tag color={TXN_LABELS[t]?.color}>{TXN_LABELS[t]?.label ?? t}</Tag>,
    },
    ...(!warehouseId ? [{ title: 'Warehouse', dataIndex: 'warehouse_name' }] : []),
    {
      title: 'Reference',
      key: 'ref',
      render: (_, r) => {
        if (r.kind) return null;
        const path = REF_PATHS[r.ref_type];
        const label = r.note || `${r.ref_type.replace(/_/g, ' ').toLowerCase()} #${r.ref_id ?? ''}`;
        if (r.reversal_of_id) return <Typography.Text type="secondary">Reversal of entry #{r.reversal_of_id}</Typography.Text>;
        return path && r.ref_id ? <Link to={`${path}/${r.ref_id}`}>{label}</Link> : label;
      },
    },
    { title: right('In'), dataIndex: 'qty_in', render: (v: string) => (compare(v, 0) ? <QtyText value={v} /> : null) },
    { title: right('Out'), dataIndex: 'qty_out', render: (v: string) => (compare(v, 0) ? <QtyText value={v} /> : null) },
    { title: right('Balance'), dataIndex: 'running_balance', render: (v: string) => <strong><QtyText value={v} /></strong> },
    { title: right('Unit cost'), dataIndex: 'unit_cost', render: (v: string) => (v ? <MoneyText value={v} scale={4} /> : null) },
    { title: 'By', dataIndex: 'created_by_name', render: (v: string | null) => v ?? '' },
  ];

  return (
    <>
      <PageHeader
        title="Product Stock Ledger"
        subtitle={data ? `${data.product_code} ${data.product_name}` : 'Every stock movement of one product.'}
      />
      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        <div style={{ width: 320, maxWidth: '100%' }}>
          <ProductSelect
            value={productId}
            valueLabel={data ? `${data.product_code} ${data.product_name}` : undefined}
            placeholder="Choose a product"
            onPick={(p) => set({ product_id: p?.id })}
          />
        </div>
        <Select
          allowClear
          placeholder="All warehouses"
          style={{ width: 200 }}
          value={warehouseId}
          options={(lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }))}
          onChange={(v?: number) => set({ warehouse_id: v })}
        />
        <DatePicker.RangePicker
          allowEmpty={[true, true]}
          value={[from ? dayjs(from) : null, to ? dayjs(to) : null]}
          onChange={(v) => set({ from: v?.[0]?.format('YYYY-MM-DD'), to: v?.[1]?.format('YYYY-MM-DD') })}
        />
      </Flex>

      {!productId ? (
        <Empty description="Choose a product to see its stock movements" style={{ marginTop: 48 }} />
      ) : (
        <PagedTable<Row>
          query={ledger}
          columns={columns}
          dataSource={rows}
          page={page}
          pageSize={pageSize}
          onPageChange={(p, ps) => set({ page: p, page_size: ps })}
          emptyText="No movements in this period"
          totalLabel="movements"
          onRow={(r) => ({ style: r.kind ? { background: 'var(--ant-color-fill-quaternary, #fafafa)' } : undefined })}
          summary={() =>
            data ? (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={warehouseId ? 5 : 6} align="right">
                  <strong>Closing balance{to ? ` on ${dayjs(to).format('DD MMM YYYY')}` : ''}</strong>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={1}>
                  <strong><QtyText value={data.closing_balance} /></strong>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={2} colSpan={2} />
              </Table.Summary.Row>
            ) : null
          }
        />
      )}
    </>
  );
}
