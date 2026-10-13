import { Flex, Input, Select, Switch, Table, Tag, Typography } from 'antd';
import type { TableProps } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { INVENTORY } from '../../api/inventory';
import type { StockPage, StockRow } from '../../api/inventory';
import { useLookups } from '../../api/master';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import QtyText from '../../components/QtyText';
import { useList } from '../../hooks/useApi';
import { formatDecimal } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

export default function CurrentStockPage() {
  const lookups = useLookups();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState<string>();
  const [warehouseId, setWarehouseId] = useState<number>();
  const [categoryId, setCategoryId] = useState<number>();
  const [lowStock, setLowStock] = useState(false);

  const list = useList<StockRow>(INVENTORY.stock, {
    page,
    page_size: pageSize,
    search,
    warehouse_id: warehouseId,
    category_id: categoryId,
    low_stock: lowStock || undefined,
  });
  const data = list.data as StockPage | undefined;
  const reset = () => setPage(1);

  const columns: TableProps<StockRow>['columns'] = [
    {
      title: 'Product',
      key: 'product',
      render: (_, r) => (
        <Link to={`/inventory/ledger?product_id=${r.product_id}&warehouse_id=${r.warehouse_id}`} title="Open stock ledger">
          <Typography.Text code>{r.product_code}</Typography.Text> {r.product_name}
        </Link>
      ),
    },
    { title: 'Category', dataIndex: 'category_name' },
    { title: 'Unit', dataIndex: 'unit_code' },
    { title: 'Warehouse', dataIndex: 'warehouse_name' },
    {
      title: right('On hand'),
      key: 'on_hand',
      render: (_, r) => (
        <Flex justify="flex-end" gap={6} align="center">
          {r.is_low && <Tag color="red" style={{ marginInlineEnd: 0 }}>Low</Tag>}
          <QtyText value={r.qty_on_hand} />
        </Flex>
      ),
    },
    { title: right('Reserved'), dataIndex: 'qty_reserved', render: (v: string) => <QtyText value={v} /> },
    { title: right('Available'), dataIndex: 'qty_available', render: (v: string) => <strong><QtyText value={v} /></strong> },
    { title: right('Avg cost'), dataIndex: 'avg_cost', render: (v: string) => <MoneyText value={v} scale={4} /> },
    { title: right('Value'), dataIndex: 'value', render: (v: string) => <MoneyText value={v} strong /> },
  ];

  return (
    <>
      <PageHeader
        title="Current Stock"
        subtitle={
          <>
            Inventory value{warehouseId || categoryId || search || lowStock ? ' (filtered)' : ''}:{' '}
            <Typography.Text strong style={{ fontSize: 16 }}>
              {data ? formatDecimal(data.total_value, 2) : '…'}
            </Typography.Text>
          </>
        }
      />
      <Flex gap={8} wrap align="center" style={{ marginBottom: 16 }}>
        <Input.Search
          allowClear
          placeholder="Search product name or code"
          style={{ width: 260, maxWidth: '100%' }}
          onSearch={(v) => {
            setSearch(v.trim() || undefined);
            reset();
          }}
        />
        <Select
          allowClear
          placeholder="Warehouse"
          style={{ width: 180 }}
          options={(lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }))}
          onChange={(v?: number) => {
            setWarehouseId(v);
            reset();
          }}
        />
        <Select
          allowClear
          placeholder="Category"
          style={{ width: 180 }}
          options={(lookups.data?.categories ?? []).map((c) => ({ label: c.name, value: c.id }))}
          onChange={(v?: number) => {
            setCategoryId(v);
            reset();
          }}
        />
        <Flex gap={6} align="center">
          <Switch
            checked={lowStock}
            onChange={(v) => {
              setLowStock(v);
              reset();
            }}
            aria-label="Low stock only"
          />
          <span>Low stock only</span>
        </Flex>
      </Flex>
      {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      <Table<StockRow>
        rowKey={(r) => `${r.product_id}-${r.warehouse_id}`}
        size="middle"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={list.isFetching}
        scroll={{ x: 'max-content' }}
        locale={{
          emptyText: list.isError
            ? 'Could not load data'
            : lowStock
              ? 'No products are at or below their reorder level'
              : 'No stock yet. Receive goods or post an adjustment to add stock.',
        }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (t) => `${t} rows`,
          onChange: (p, ps) => {
            setPage(ps !== pageSize ? 1 : p);
            setPageSize(ps);
          },
        }}
      />
    </>
  );
}
