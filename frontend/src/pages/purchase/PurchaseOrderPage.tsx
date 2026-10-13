import { ArrowLeftOutlined, CheckOutlined, CloseOutlined, InboxOutlined, RollbackOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Skeleton,
  Statistic,
  Steps,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { errorMessage } from '../../api/client';
import { INVENTORY, useStockOf } from '../../api/inventory';
import { PURCHASE, purchaseApi } from '../../api/purchase';
import type { GoodsReceiptDoc, PoItem, PurchaseOrderDetail, ReceiptItem } from '../../api/purchase';
import ApprovalNotice from '../../components/ApprovalNotice';
import ConfirmButton from '../../components/ConfirmButton';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import QtyText from '../../components/QtyText';
import StatusTag from '../../components/StatusTag';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { compare, formatDecimal, multiply, sum } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

const STEP_ORDER = ['draft', 'approved', 'partially_received', 'received'];

function StatusSteps({ po }: { po: PurchaseOrderDetail }) {
  const cancelled = po.status === 'cancelled' || po.status === 'rejected';
  const current = po.status === 'pending_approval' ? 0 : STEP_ORDER.indexOf(po.status);
  return (
    <Steps
      size="small"
      current={cancelled ? 1 : current}
      status={cancelled ? 'error' : po.status === 'received' ? 'finish' : 'process'}
      items={[
        { title: 'Draft', content: <DateText value={po.created_at} /> },
        cancelled
          ? { title: po.status === 'rejected' ? 'Rejected' : 'Cancelled' }
          : {
              title: po.status === 'pending_approval' ? 'Pending approval' : 'Approved',
              content: po.approved_at ? <DateText value={po.approved_at} /> : undefined,
            },
        { title: 'Partially received' },
        { title: 'Received' },
      ]}
      style={{ marginBottom: 16 }}
    />
  );
}

// --- Receive goods dialog ------------------------------------------------------------------

interface ReceiveRow {
  item: PoItem;
  qty: string | null;
  unit_cost: string | null;
}

function ReceiveModal({ po, open, onClose }: { po: PurchaseOrderDetail; open: boolean; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<ReceiveRow[]>([]);
  const [form] = Form.useForm<{ receipt_date: Dayjs; notes: string }>();

  const reset = () =>
    setRows(
      po.items
        .filter((i) => compare(i.remaining_qty, 0) > 0)
        .map((item) => ({ item, qty: item.remaining_qty, unit_cost: item.unit_cost })),
    );

  const mutation = useMutation({
    mutationFn: (v: { receipt_date: Dayjs; notes: string }) =>
      purchaseApi.receive(po.id, {
        receipt_date: v.receipt_date.format('YYYY-MM-DD'),
        notes: v.notes ?? '',
        items: rows
          .filter((r) => r.qty && compare(r.qty, 0) > 0)
          .map((r) => ({ po_item_id: r.item.id, qty: r.qty!, unit_cost: r.unit_cost ?? undefined })),
      }),
    meta: { silent: true },
    onSuccess: async (grn) => {
      message.success(`${grn.grn_number} received: ${formatDecimal(grn.total, 2)} credited to the supplier`);
      onClose();
      await Promise.all(
        [PURCHASE.orders, PURCHASE.receipts, INVENTORY.stock, '/suppliers'].map((k) => queryClient.invalidateQueries({ queryKey: [k] })),
      );
    },
    onError: (error) => applyServerErrors(form, error),
  });

  const update = (id: number, patch: Partial<ReceiveRow>) =>
    setRows((prev) => prev.map((r) => (r.item.id === id ? { ...r, ...patch } : r)));
  const chosen = rows.filter((r) => r.qty && compare(r.qty, 0) > 0);
  const gross = sum(chosen.map((r) => multiply(r.qty, r.unit_cost, 2)), 2);
  const over = rows.some((r) => r.qty && compare(r.qty, r.item.remaining_qty) > 0);

  const columns: TableProps<ReceiveRow>['columns'] = [
    { title: 'Product', key: 'p', render: (_, r) => <>{r.item.product_code} {r.item.product_name}</> },
    { title: right('Remaining'), key: 'rem', render: (_, r) => <QtyText value={r.item.remaining_qty} unit={r.item.unit_code} /> },
    {
      title: 'Receive now',
      key: 'qty',
      width: 150,
      render: (_, r) => (
        <InputNumber<string>
          stringMode
          min="0"
          max={r.item.remaining_qty}
          precision={3}
          value={r.qty}
          onChange={(qty) => update(r.item.id, { qty })}
          status={r.qty && compare(r.qty, r.item.remaining_qty) > 0 ? 'error' : undefined}
          style={{ width: '100%' }}
          aria-label={`Receive qty ${r.item.product_code}`}
        />
      ),
    },
    {
      title: 'Unit cost',
      key: 'cost',
      width: 160,
      render: (_, r) => (
        <InputNumber<string>
          stringMode
          min="0"
          precision={4}
          value={r.unit_cost}
          onChange={(unit_cost) => update(r.item.id, { unit_cost })}
          style={{ width: '100%' }}
          aria-label={`Unit cost ${r.item.product_code}`}
        />
      ),
    },
    { title: right('Amount'), key: 'amt', render: (_, r) => <MoneyText value={multiply(r.qty, r.unit_cost, 2)} /> },
  ];

  return (
    <Modal
      title={`Receive goods: ${po.po_number}`}
      open={open}
      width={920}
      onCancel={onClose}
      afterOpenChange={(visible) => {
        if (visible) {
          reset();
          form.resetFields();
          mutation.reset();
        }
      }}
      okText="Receive"
      okButtonProps={{ disabled: !chosen.length || over }}
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      {mutation.isError && (
        <Alert type="error" showIcon title="Could not receive" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />
      )}
      <Typography.Paragraph type="secondary">
        Into <strong>{po.warehouse_name}</strong>. Enter what actually arrived; leave 0 for lines not delivered yet. Unit cost
        defaults to the order price and can be changed if the supplier billed differently.
      </Typography.Paragraph>
      <Table<ReceiveRow> rowKey={(r) => r.item.id} size="small" pagination={false} columns={columns} dataSource={rows} />
      <Form form={form} layout="inline" initialValues={{ receipt_date: dayjs(), notes: '' }} onFinish={(v) => mutation.mutate(v)} style={{ marginTop: 16 }}>
        <Form.Item name="receipt_date" label="Receipt date" rules={[{ required: true }]}>
          <DatePicker allowClear={false} />
        </Form.Item>
        <Form.Item name="notes" label="Notes" style={{ flex: 1 }}>
          <Input placeholder="e.g. supplier invoice number" />
        </Form.Item>
      </Form>
      <Flex justify="flex-end" style={{ marginTop: 12 }}>
        <Typography.Text>
          Gross value: <strong>{formatDecimal(gross, 2)}</strong>
          {compare(po.discount, 0) > 0 && <Typography.Text type="secondary"> (share of the {formatDecimal(po.discount, 2)} discount is applied on save)</Typography.Text>}
        </Typography.Text>
      </Flex>
    </Modal>
  );
}

// --- Return dialog -------------------------------------------------------------------------

interface ReturnRow {
  item: ReceiptItem;
  qty: string | null;
}

function AvailableNow({ productId, warehouseId, qty }: { productId: number; warehouseId: number; qty: string | null }) {
  const stock = useStockOf(productId, warehouseId);
  const available = stock.data?.qty_available ?? '0';
  const short = qty && compare(qty, available) > 0;
  return (
    <span style={{ color: short ? 'var(--ant-color-error, #ff4d4f)' : undefined }}>
      <QtyText value={stock.isPending ? null : available} />
    </span>
  );
}

function ReturnModal({ grn, onClose }: { grn: GoodsReceiptDoc | null; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<ReturnRow[]>([]);
  const [form] = Form.useForm<{ return_date: Dayjs; notes: string }>();

  const mutation = useMutation({
    mutationFn: (v: { return_date: Dayjs; notes: string }) =>
      purchaseApi.returnGoods(grn!.id, {
        return_date: v.return_date.format('YYYY-MM-DD'),
        notes: v.notes ?? '',
        items: rows.filter((r) => r.qty && compare(r.qty, 0) > 0).map((r) => ({ grn_item_id: r.item.id, qty: r.qty! })),
      }),
    meta: { silent: true },
    onSuccess: async (ret) => {
      message.success(`${ret.prn_number}: ${formatDecimal(ret.total, 2)} debited to the supplier`);
      onClose();
      await Promise.all(
        [PURCHASE.orders, PURCHASE.receipts, PURCHASE.returns, INVENTORY.stock, '/suppliers'].map((k) =>
          queryClient.invalidateQueries({ queryKey: [k] }),
        ),
      );
    },
    onError: (error) => applyServerErrors(form, error),
  });

  const chosen = rows.filter((r) => r.qty && compare(r.qty, 0) > 0);
  const over = rows.some((r) => r.qty && compare(r.qty, r.item.returnable_qty) > 0);

  return (
    <Modal
      title={grn ? `Return to supplier: ${grn.grn_number}` : ''}
      open={grn !== null}
      width={860}
      onCancel={onClose}
      afterOpenChange={(visible) => {
        if (visible && grn) {
          setRows(grn.items.filter((i) => compare(i.returnable_qty, 0) > 0).map((item) => ({ item, qty: null })));
          form.resetFields();
          mutation.reset();
        }
      }}
      okText="Return goods"
      okButtonProps={{ danger: true, disabled: !chosen.length || over }}
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      {mutation.isError && (
        <Alert type="error" showIcon title="Could not return" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />
      )}
      {grn && (
        <>
          <Typography.Paragraph type="secondary">
            Goods leave <strong>{grn.warehouse_name}</strong> at their receipt cost. The supplier is debited the net amount
            {compare(grn.discount, 0) > 0 ? ' (after this receipt’s share of the discount)' : ''}.
          </Typography.Paragraph>
          <Table<ReturnRow>
            rowKey={(r) => r.item.id}
            size="small"
            pagination={false}
            dataSource={rows}
            columns={[
              { title: 'Product', key: 'p', render: (_, r) => <>{r.item.product_code} {r.item.product_name}</> },
              { title: right('Received'), key: 'rec', render: (_, r) => <QtyText value={r.item.qty} unit={r.item.unit_code} /> },
              { title: right('Returnable'), key: 'ret', render: (_, r) => <QtyText value={r.item.returnable_qty} /> },
              { title: right('In stock now'), key: 'stock', render: (_, r) => <AvailableNow productId={r.item.product_id} warehouseId={grn.warehouse_id} qty={r.qty} /> },
              { title: right('Cost'), key: 'cost', render: (_, r) => <MoneyText value={r.item.unit_cost} scale={4} /> },
              {
                title: 'Return qty',
                key: 'qty',
                width: 140,
                render: (_, r) => (
                  <InputNumber<string>
                    stringMode
                    min="0"
                    precision={3}
                    value={r.qty}
                    status={r.qty && compare(r.qty, r.item.returnable_qty) > 0 ? 'error' : undefined}
                    onChange={(qty) => setRows((prev) => prev.map((x) => (x.item.id === r.item.id ? { ...x, qty } : x)))}
                    style={{ width: '100%' }}
                    aria-label={`Return qty ${r.item.product_code}`}
                  />
                ),
              },
            ]}
          />
          <Form form={form} layout="inline" initialValues={{ return_date: dayjs(), notes: '' }} onFinish={(v) => mutation.mutate(v)} style={{ marginTop: 16 }}>
            <Form.Item name="return_date" label="Return date" rules={[{ required: true }]}>
              <DatePicker allowClear={false} />
            </Form.Item>
            <Form.Item name="notes" label="Reason / notes" style={{ flex: 1 }}>
              <Input placeholder="e.g. damaged on arrival" />
            </Form.Item>
          </Form>
        </>
      )}
    </Modal>
  );
}

// --- Page ------------------------------------------------------------------------------------

function ReceiptCard({ grn, canReturn, onReturn }: { grn: GoodsReceiptDoc; canReturn: boolean; onReturn: () => void }) {
  const returnable = grn.items.some((i) => compare(i.returnable_qty, 0) > 0);
  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      title={
        <Flex gap={8} align="center" wrap>
          <strong>{grn.grn_number}</strong>
          <DateText value={grn.receipt_date} />
          {grn.is_direct && <Tag color="purple">Direct</Tag>}
          <Typography.Text type="secondary">by {grn.created_by_name}</Typography.Text>
        </Flex>
      }
      extra={
        canReturn &&
        returnable && (
          <Button size="small" icon={<RollbackOutlined />} onClick={onReturn}>
            Return
          </Button>
        )
      }
    >
      <Table<ReceiptItem>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={grn.items}
        columns={[
          { title: 'Product', key: 'p', render: (_, i) => <>{i.product_code} {i.product_name}</> },
          { title: right('Qty'), dataIndex: 'qty', render: (v: string, i) => <QtyText value={v} unit={i.unit_code} /> },
          { title: right('Unit cost'), dataIndex: 'unit_cost', render: (v: string) => <MoneyText value={v} scale={4} /> },
          { title: right('Amount'), dataIndex: 'line_total', render: (v: string) => <MoneyText value={v} /> },
          { title: right('Returned'), dataIndex: 'returned_qty', render: (v: string) => (compare(v, 0) > 0 ? <QtyText value={v} /> : null) },
        ]}
      />
      <Flex justify="flex-end" gap={24} style={{ marginTop: 8 }} wrap>
        <span>Gross {formatDecimal(grn.subtotal, 2)}</span>
        {compare(grn.discount, 0) > 0 && <span>Discount −{formatDecimal(grn.discount, 2)}</span>}
        <strong>Credited {formatDecimal(grn.total, 2)}</strong>
      </Flex>
      {grn.returns.map((r) => (
        <Alert
          key={r.id}
          type="warning"
          style={{ marginTop: 8 }}
          title={
            <>
              <strong>{r.prn_number}</strong> on <DateText value={r.return_date} />: returned{' '}
              {r.items.map((i) => `${formatDecimal(i.qty, 3, true)} ${i.unit_code} ${i.product_code}`).join(', ')}, debited{' '}
              <strong>{formatDecimal(r.total, 2)}</strong>
              {r.notes ? ` (${r.notes})` : ''}
            </>
          }
        />
      ))}
    </Card>
  );
}

export default function PurchaseOrderPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const canApprove = usePermission('purchase_order.edit');
  const canCancel = usePermission('purchase_order.delete');
  const canReceive = usePermission('goods_receipt.create');
  const canReturn = usePermission('purchase_return.create');
  const [receiving, setReceiving] = useState(false);
  const [returning, setReturning] = useState<GoodsReceiptDoc | null>(null);

  const po = useQuery({
    queryKey: [PURCHASE.orders, 'detail', id],
    queryFn: () => purchaseApi.order(id),
    enabled: Number.isInteger(id),
  });

  const action = useMutation({
    mutationFn: (what: 'approve' | 'cancel') => purchaseApi.action(id, what),
    meta: { silent: true },
    onSuccess: async (result, what) => {
      queryClient.setQueryData([PURCHASE.orders, 'detail', id], result);
      message.success(what === 'approve' ? `${result.po_number} ${result.status === 'approved' ? 'approved' : 'sent for approval'}` : `${result.po_number} cancelled`);
      await queryClient.invalidateQueries({ queryKey: [PURCHASE.orders] });
    },
  });

  if (po.isError) return <ErrorState error={po.error} onRetry={() => po.refetch()} />;
  if (!po.data) return <Skeleton active />;
  const d = po.data;
  const receivable = (d.status === 'approved' || d.status === 'partially_received') && d.items.some((i) => compare(i.remaining_qty, 0) > 0);
  const nothingReceived = d.items.every((i) => compare(i.received_qty, 0) === 0);

  const columns: TableProps<PoItem>['columns'] = [
    {
      title: 'Product',
      key: 'p',
      render: (_, i) => (
        <Link to={`/inventory/ledger?product_id=${i.product_id}&warehouse_id=${d.warehouse_id}`}>
          <Typography.Text code>{i.product_code}</Typography.Text> {i.product_name}
        </Link>
      ),
    },
    { title: right('Ordered'), dataIndex: 'qty', render: (v: string, i) => <QtyText value={v} unit={i.unit_code} /> },
    { title: right('Received'), dataIndex: 'received_qty', render: (v: string) => <QtyText value={v} /> },
    {
      title: right('Remaining'),
      dataIndex: 'remaining_qty',
      render: (v: string) => (compare(v, 0) > 0 ? <strong><QtyText value={v} /></strong> : <Typography.Text type="success" style={{ display: 'block', textAlign: 'right' }}>✓</Typography.Text>),
    },
    { title: right('Unit cost'), dataIndex: 'unit_cost', render: (v: string) => <MoneyText value={v} scale={4} /> },
    { title: right('Amount'), dataIndex: 'line_total', render: (v: string) => <MoneyText value={v} /> },
  ];

  return (
    <>
      <PageHeader
        title={<Flex gap={12} align="center">Purchase Order {d.po_number} <StatusTag status={d.status} /></Flex>}
        actions={
          <>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(PURCHASE.orders)}>Orders</Button>
            {canCancel && nothingReceived && ['draft', 'pending_approval', 'approved', 'rejected'].includes(d.status) && (
              <ConfirmButton icon={<CloseOutlined />} danger confirm={`Cancel ${d.po_number}?`} okText="Cancel order"
                loading={action.isPending && action.variables === 'cancel'} onConfirm={() => action.mutateAsync('cancel')}>
                Cancel
              </ConfirmButton>
            )}
            {canApprove && d.status === 'draft' && (
              <ConfirmButton type="primary" icon={<CheckOutlined />} confirm={`Approve ${d.po_number}?`}
                description="Approved orders can be received but no longer edited." okText="Approve"
                loading={action.isPending && action.variables === 'approve'} onConfirm={() => action.mutateAsync('approve')}>
                Approve
              </ConfirmButton>
            )}
            {canReceive && receivable && (
              <Button type="primary" icon={<InboxOutlined />} onClick={() => setReceiving(true)}>
                Receive goods
              </Button>
            )}
          </>
        }
      />
      {action.isError && (
        <Alert type="error" showIcon closable={{ onClose: () => action.reset() }} title="Action failed" description={errorMessage(action.error)} style={{ marginBottom: 16 }} />
      )}
      {d.status === 'draft' && (
        <Alert type="info" showIcon title="Draft: edit it from the order list, then approve it to start receiving." style={{ marginBottom: 16 }} />
      )}
      <ApprovalNotice documentType="PURCHASE_ORDER" number={d.po_number} status={d.status} />
      <StatusSteps po={d} />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={17}>
          <Card size="small">
            <Descriptions
              size="small"
              column={{ xs: 1, md: 2 }}
              items={[
                { label: 'Supplier', children: <Link to={`/suppliers/${d.supplier_id}/statement`}>{d.supplier_code} {d.supplier_name}</Link> },
                { label: 'Receive into', children: d.warehouse_name },
                { label: 'Order date', children: <DateText value={d.order_date} /> },
                { label: 'Expected', children: <DateText value={d.expected_date} /> },
                { label: 'Created by', children: d.created_by_name },
                { label: 'Approved by', children: d.approved_by_name ?? '—' },
                ...(d.notes ? [{ label: 'Notes', children: d.notes, span: 'filled' as const }] : []),
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={7}>
          <Card size="small">
            <Statistic title="Supplier current due (payable)" value={formatDecimal(d.supplier_due, 2)} />
          </Card>
        </Col>
      </Row>

      <Table<PoItem>
        rowKey="id"
        size="middle"
        pagination={false}
        columns={columns}
        dataSource={d.items}
        scroll={{ x: 'max-content' }}
        summary={() => (
          <>
            {[
              ['Subtotal', d.subtotal],
              ...(compare(d.discount, 0) > 0 ? [['Discount (bill only)', `-${d.discount}`]] : []),
              ['Total payable', d.total],
            ].map(([label, value], i, all) => (
              <Table.Summary.Row key={label}>
                <Table.Summary.Cell index={0} colSpan={5} align="right">
                  {i === all.length - 1 ? <strong>{label}</strong> : label}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={1}>
                  <MoneyText value={value} strong={i === all.length - 1} />
                </Table.Summary.Cell>
              </Table.Summary.Row>
            ))}
          </>
        )}
      />

      <Typography.Title level={5} style={{ marginTop: 24 }}>
        Goods receipts
      </Typography.Title>
      {d.receipts.length === 0 ? (
        <Empty description="Nothing received yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        d.receipts.map((g) => <ReceiptCard key={g.id} grn={g} canReturn={canReturn} onReturn={() => setReturning(g)} />)
      )}

      <ReceiveModal po={d} open={receiving} onClose={() => setReceiving(false)} />
      <ReturnModal grn={returning} onClose={() => setReturning(null)} />
    </>
  );
}
