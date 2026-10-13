import { DollarOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, DatePicker, Drawer, Flex, Form, Input, InputNumber, Select, Table, Tag, Typography } from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';

import { MASTER, PRODUCT_TYPE_COLORS, PRODUCT_TYPE_LABELS, masterApi, useLookups } from '../../api/master';
import type { PriceRecord, ProductRecord, ProductType } from '../../api/master';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { notifyError } from '../../utils/notify';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

function PriceDrawer({ product, onClose }: { product: ProductRecord | null; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const canCreate = usePermission('price.create');
  const [form] = Form.useForm<{ price: string; effective_from: Dayjs }>();

  const history = useQuery({
    queryKey: [MASTER.products, 'prices', product?.id],
    queryFn: () => masterApi.prices(product!.id),
    enabled: product !== null,
  });
  const add = useMutation({
    mutationFn: (v: { price: string; effective_from: Dayjs }) =>
      masterApi.addPrice(product!.id, { price: v.price, effective_from: v.effective_from.format('YYYY-MM-DD') }),
    meta: { silent: true },
    onSuccess: async (row) => {
      message.success(`New price ${row.price} from ${dayjs(row.effective_from).format('DD MMM YYYY')}`);
      form.resetFields();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: [MASTER.products] }),
        queryClient.invalidateQueries({ queryKey: [MASTER.prices] }),
      ]);
    },
    onError: (error) => {
      if (!applyServerErrors(form, error)) notifyError(error, 'Could not save price');
    },
  });

  const columns: TableProps<PriceRecord>['columns'] = [
    { title: 'Effective from', dataIndex: 'effective_from', render: (v: string) => <DateText value={v} /> },
    { title: right('Price'), dataIndex: 'price', render: (v: string) => <MoneyText value={v} /> },
    {
      title: 'Status',
      key: 'status',
      render: (_, p) =>
        p.is_current ? <Tag color="green">Current</Tag> : dayjs(p.effective_from).isAfter(dayjs(), 'day') ? <Tag color="blue">Scheduled</Tag> : <Tag>Past</Tag>,
    },
    { title: 'Entered by', key: 'by', render: (_, p) => <>{p.created_by_name ?? '—'}<br /><Typography.Text type="secondary"><DateText value={p.created_at} withTime /></Typography.Text></> },
  ];

  return (
    <Drawer title={product ? `Price: ${product.code} ${product.name}` : ''} open={product !== null} onClose={onClose} size={600} destroyOnHidden>
      {canCreate && (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ effective_from: dayjs() }}
          onFinish={(v) => add.mutate(v)}
          disabled={add.isPending}
          style={{ marginBottom: 24 }}
        >
          <Flex gap={12} wrap align="flex-end">
            <Form.Item name="price" label="New price" rules={[{ required: true, message: 'Enter a price' }]} style={{ marginBottom: 0 }}>
              <InputNumber<string> stringMode min="0" precision={2} style={{ width: 180 }} autoFocus />
            </Form.Item>
            <Form.Item name="effective_from" label="Effective from" rules={[{ required: true, message: 'Pick a date' }]} style={{ marginBottom: 0 }}>
              <DatePicker allowClear={false} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={add.isPending}>
              Add price
            </Button>
          </Flex>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            Prices are never edited: a new row takes over from its date. Future dates are scheduled.
          </Typography.Paragraph>
        </Form>
      )}
      <Typography.Title level={5}>History</Typography.Title>
      {history.isError ? (
        <ErrorState error={history.error} onRetry={() => history.refetch()} />
      ) : (
        <Table<PriceRecord>
          rowKey="id"
          size="small"
          pagination={false}
          loading={history.isPending}
          columns={columns}
          dataSource={history.data ?? []}
          locale={{ emptyText: 'No prices yet' }}
        />
      )}
    </Drawer>
  );
}

export default function PriceListPage() {
  const lookups = useLookups();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState<string>();
  const [categoryId, setCategoryId] = useState<number>();
  const [productType, setProductType] = useState<ProductType>();
  const [selected, setSelected] = useState<ProductRecord | null>(null);

  const list = useList<ProductRecord>(MASTER.prices, {
    page,
    page_size: pageSize,
    search,
    category_id: categoryId,
    product_type: productType,
  });

  const columns: TableProps<ProductRecord>['columns'] = [
    { title: 'Code', dataIndex: 'code', width: 100, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    { title: 'Product', dataIndex: 'name' },
    { title: 'Category', dataIndex: 'category_name' },
    { title: 'Type', dataIndex: 'product_type', render: (t: ProductType) => <Tag color={PRODUCT_TYPE_COLORS[t]}>{PRODUCT_TYPE_LABELS[t]}</Tag> },
    { title: 'Unit', dataIndex: 'unit_code' },
    {
      title: right('Current price'),
      dataIndex: 'current_price',
      render: (v: string | null) => (v ? <MoneyText value={v} strong /> : <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'right' }}>Not set</Typography.Text>),
    },
    { title: 'Since', dataIndex: 'price_effective_from', render: (v: string | null) => <DateText value={v} /> },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, p) => (
        <Button size="small" icon={<DollarOutlined />} onClick={() => setSelected(p)}>
          Update price
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Product Price List" subtitle="Current selling price of every active product." />
      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        <Input.Search
          allowClear
          placeholder="Search name or code"
          style={{ width: 280, maxWidth: '100%' }}
          onSearch={(v) => {
            setSearch(v.trim() || undefined);
            setPage(1);
          }}
        />
        <Select
          allowClear
          placeholder="Category"
          style={{ width: 180 }}
          options={(lookups.data?.categories ?? []).map((c) => ({ label: c.name, value: c.id }))}
          onChange={(v?: number) => {
            setCategoryId(v);
            setPage(1);
          }}
        />
        <Select
          allowClear
          placeholder="Type"
          style={{ width: 160 }}
          options={Object.entries(PRODUCT_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
          onChange={(v?: ProductType) => {
            setProductType(v);
            setPage(1);
          }}
        />
      </Flex>
      {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      <Table<ProductRecord>
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={list.data?.items ?? []}
        loading={list.isFetching}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: list.isError ? 'Could not load data' : 'No products found' }}
        pagination={{
          current: page,
          pageSize,
          total: list.data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (t) => `${t} products`,
          onChange: (p, ps) => {
            setPage(ps !== pageSize ? 1 : p);
            setPageSize(ps);
          },
        }}
      />
      <PriceDrawer product={selected} onClose={() => setSelected(null)} />
    </>
  );
}
