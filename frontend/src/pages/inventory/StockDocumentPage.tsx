import { ArrowLeftOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Card, Descriptions, Skeleton, Table, Tag, Typography } from 'antd';
import type { TableProps } from 'antd';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { errorMessage } from '../../api/client';
import { INVENTORY, inventoryApi } from '../../api/inventory';
import type { AdjustmentDoc, CountDoc, StockDoc, TransferDoc } from '../../api/inventory';
import ApprovalNotice from '../../components/ApprovalNotice';
import ConfirmButton from '../../components/ConfirmButton';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import QtyText from '../../components/QtyText';
import StatusTag from '../../components/StatusTag';
import { usePermission } from '../../hooks/usePermission';
import { compare, multiply, sum } from '../../utils/decimal';

export type StockDocKind = 'transfers' | 'adjustments' | 'counts';

const CONFIG: Record<StockDocKind, { endpoint: string; label: string; permission: string; list: string }> = {
  transfers: { endpoint: INVENTORY.transfers, label: 'Stock Transfer', permission: 'stock_transfer', list: 'Transfers' },
  adjustments: { endpoint: INVENTORY.adjustments, label: 'Stock Adjustment', permission: 'stock_adjustment', list: 'Adjustments' },
  counts: { endpoint: INVENTORY.counts, label: 'Physical Count', permission: 'stock_count', list: 'Counts' },
};

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;
type Item = StockDoc['items'][number];

function lineValue(item: Item & { qty?: string; variance?: string }): string | null {
  if (!item.unit_cost) return null;
  const qty = item.qty ?? (item.variance ? item.variance.replace('-', '') : null);
  return qty ? multiply(qty, item.unit_cost, 2) : null;
}

function itemColumns(kind: StockDocKind, doc: StockDoc): TableProps<Item>['columns'] {
  const posted = doc.status === 'posted';
  const product = {
    title: 'Product',
    key: 'product',
    render: (_: unknown, i: Item) => (
      <Link to={`/inventory/ledger?product_id=${i.product_id}`}>
        <Typography.Text code>{i.product_code}</Typography.Text> {i.product_name}
      </Link>
    ),
  };
  const cost = posted
    ? [
        { title: right('Unit cost'), dataIndex: 'unit_cost', render: (v: string | null) => <MoneyText value={v} scale={4} /> },
        { title: right('Value'), key: 'value', render: (_: unknown, i: Item) => <MoneyText value={lineValue(i)} /> },
      ]
    : [];

  if (kind === 'counts') {
    return [
      product,
      { title: right('System qty (snapshot)'), dataIndex: 'system_qty', render: (v: string) => <QtyText value={v} /> },
      { title: right('Counted'), dataIndex: 'counted_qty', render: (v: string, i: Item) => <QtyText value={v} unit={i.unit_code} /> },
      {
        title: right('Variance'),
        dataIndex: 'variance',
        render: (v: string) => {
          const sign = compare(v, 0);
          return (
            <div style={{ textAlign: 'right' }}>
              {sign === 0 ? (
                <Typography.Text type="secondary">0</Typography.Text>
              ) : (
                <Tag color={sign < 0 ? 'red' : 'green'} style={{ marginInlineEnd: 0, fontWeight: 600 }}>
                  {sign > 0 ? '+' : ''}
                  {Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 })}
                </Tag>
              )}
            </div>
          );
        },
      },
      ...(doc.status === 'draft'
        ? [
            {
              title: right('Now on hand'),
              key: 'current',
              render: (_: unknown, i: Item) => {
                const item = i as CountDoc['items'][number];
                const moved = item.current_qty !== null && compare(item.current_qty, item.system_qty) !== 0;
                return (
                  <div style={{ textAlign: 'right' }}>
                    <QtyText value={item.current_qty} />
                    {moved && <Tag color="gold" style={{ marginInlineEnd: 0, marginTop: 2 }}>moved since snapshot</Tag>}
                  </div>
                );
              },
            },
          ]
        : []),
      ...cost,
    ];
  }
  return [
    product,
    ...(kind === 'adjustments'
      ? [
          {
            title: 'Change',
            dataIndex: 'direction',
            render: (d: string) => (d === 'increase' ? <Tag color="green">Increase</Tag> : <Tag color="red">Decrease</Tag>),
          },
        ]
      : []),
    { title: right('Qty'), dataIndex: 'qty', render: (v: string, i: Item) => <QtyText value={v} unit={i.unit_code} /> },
    ...(kind === 'adjustments' && !posted
      ? [{ title: right('Unit cost'), dataIndex: 'unit_cost', render: (v: string | null) => (v ? <MoneyText value={v} scale={4} /> : right('avg / default')) }]
      : []),
    ...cost,
  ];
}

function headerItems(kind: StockDocKind, doc: StockDoc) {
  const common = [
    { label: 'Status', children: <StatusTag status={doc.status} /> },
    { label: 'Created by', children: <>{doc.created_by_name} · <DateText value={doc.created_at} withTime /></> },
    ...(doc.posted_at ? [{ label: 'Posted by', children: <>{doc.posted_by_name} · <DateText value={doc.posted_at} withTime /></> }] : []),
    ...(doc.note ? [{ label: 'Note', children: doc.note }] : []),
  ];
  if (kind === 'transfers') {
    const t = doc as TransferDoc;
    return [
      { label: 'Date', children: <DateText value={t.transfer_date} /> },
      { label: 'From', children: t.from_warehouse_name },
      { label: 'To', children: t.to_warehouse_name },
      ...common,
    ];
  }
  if (kind === 'adjustments') {
    const a = doc as AdjustmentDoc;
    return [
      { label: 'Date', children: <DateText value={a.adjustment_date} /> },
      { label: 'Warehouse', children: a.warehouse_name },
      { label: 'Reason', children: a.reason },
      ...common,
    ];
  }
  const c = doc as CountDoc;
  return [
    { label: 'Count date', children: <DateText value={c.count_date} /> },
    { label: 'Warehouse', children: c.warehouse_name },
    ...common,
  ];
}

export default function StockDocumentPage({ kind }: { kind: StockDocKind }) {
  const cfg = CONFIG[kind];
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const canPost = usePermission(`${cfg.permission}.edit`);
  const canCancel = usePermission(`${cfg.permission}.delete`);
  const [moved, setMoved] = useState<number[]>([]);

  const doc = useQuery({
    queryKey: [cfg.endpoint, 'detail', id],
    queryFn: () => inventoryApi.document<StockDoc>(cfg.endpoint, id),
    enabled: Number.isInteger(id),
  });

  const refresh = () =>
    Promise.all(
      [cfg.endpoint, INVENTORY.stock, INVENTORY.ledger].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    );

  // Errors (e.g. INSUFFICIENT_STOCK) are shown inline above the lines, not just as a toast.
  const action = useMutation({
    mutationFn: (what: 'post' | 'cancel') => inventoryApi.action<StockDoc>(cfg.endpoint, id, what),
    meta: { silent: true },
    onSuccess: async (result, what) => {
      queryClient.setQueryData([cfg.endpoint, 'detail', id], result);
      if (what === 'post') setMoved((result as CountDoc).moved_since_snapshot ?? []);
      if (what === 'post' && result.status === 'pending_approval') message.warning(`${result.number} needs approval: stock moves once it is approved`);
      else message.success(what === 'post' ? `${result.number} posted` : `${result.number} cancelled`);
      await refresh();
    },
  });

  if (doc.isError) return <ErrorState error={doc.error} onRetry={() => doc.refetch()} />;
  if (!doc.data) return <Skeleton active />;
  const d = doc.data;
  // Nothing posted yet: draft, waiting for approval, or rejected by the approver.
  const editableStatus = ['draft', 'pending_approval', 'rejected'].includes(d.status);
  const totalValue =
    d.status === 'posted' ? sum(d.items.map((i) => lineValue(i as Item & { qty?: string }) ?? '0'), 2) : null;

  return (
    <>
      <PageHeader
        title={<>{cfg.label} {d.number}</>}
        actions={
          <>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(cfg.endpoint)}>
              {cfg.list}
            </Button>
            {canCancel && editableStatus && (
              <ConfirmButton
                icon={<CloseOutlined />}
                danger
                confirm={`Cancel ${d.number}?`}
                description="Nothing has been posted; the document is kept as cancelled."
                okText="Cancel document"
                loading={action.isPending && action.variables === 'cancel'}
                onConfirm={() => action.mutateAsync('cancel')}
              >
                Cancel
              </ConfirmButton>
            )}
            {canPost && d.status === 'draft' && (
              <ConfirmButton
                type="primary"
                icon={<CheckOutlined />}
                confirm={`Post ${d.number}?`}
                description="Stock moves immediately. Posted documents cannot be edited."
                okText="Post"
                loading={action.isPending && action.variables === 'post'}
                onConfirm={() => action.mutateAsync('post')}
              >
                Post
              </ConfirmButton>
            )}
          </>
        }
      />

      {action.isError && (
        <Alert
          type="error"
          showIcon
          closable={{ onClose: () => action.reset() }}
          title={action.variables === 'post' ? 'Could not post' : 'Could not cancel'}
          description={errorMessage(action.error)}
          style={{ marginBottom: 16 }}
        />
      )}
      {kind === 'adjustments' && <ApprovalNotice documentType="STOCK_ADJUSTMENT" number={d.number} status={d.status} />}
      {moved.length > 0 && (
        <Alert
          type="info"
          showIcon
          title="Stock changed for some products after the count snapshot"
          description="The counted variance was applied on top of those movements."
          style={{ marginBottom: 16 }}
        />
      )}

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={{ xs: 1, md: 3 }} items={headerItems(kind, d)} />
      </Card>

      <Table<Item>
        rowKey="id"
        size="middle"
        pagination={false}
        columns={itemColumns(kind, d)}
        dataSource={d.items}
        scroll={{ x: 'max-content' }}
        summary={
          totalValue
            ? () => (
                <Table.Summary.Row>
                  <Table.Summary.Cell index={0} colSpan={(itemColumns(kind, d)?.length ?? 1) - 1} align="right">
                    <strong>Total value</strong>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={1}>
                    <MoneyText value={totalValue} strong />
                  </Table.Summary.Cell>
                </Table.Summary.Row>
              )
            : undefined
        }
      />
    </>
  );
}
