import {
  ArrowLeftOutlined,
  CarOutlined,
  CheckOutlined,
  CloseOutlined,
  FileDoneOutlined,
  LockOutlined,
  UnlockOutlined,
} from '@ant-design/icons';
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
  Switch,
  Table,
  Typography,
} from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { errorMessage } from '../../api/client';
import { SALES, SALES_INVALIDATES, salesApi } from '../../api/sales';
import type { DeliveryDoc, Invoice, ReserveLine, SoDetail, SoItem } from '../../api/sales';
import ConfirmButton from '../../components/ConfirmButton';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import QtyText from '../../components/QtyText';
import StatusTag from '../../components/StatusTag';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { notifyError } from '../../utils/notify';
import { compare, formatDecimal, multiply, sum } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;
const OPEN = ['confirmed', 'partially_delivered'];

function StatusSteps({ so }: { so: SoDetail }) {
  const cancelled = so.status === 'cancelled';
  const order = ['draft', 'confirmed', 'partially_delivered', 'delivered'];
  return (
    <Steps
      size="small"
      current={cancelled ? 1 : order.indexOf(so.status)}
      status={cancelled ? 'error' : so.status === 'delivered' ? 'finish' : 'process'}
      items={[
        { title: 'Draft', content: <DateText value={so.created_at} /> },
        cancelled ? { title: 'Cancelled' } : { title: 'Confirmed', content: so.confirmed_at ? <DateText value={so.confirmed_at} /> : undefined },
        { title: 'Partially delivered' },
        { title: 'Delivered' },
      ]}
      style={{ marginBottom: 16 }}
    />
  );
}

/** Manual "produced" figure: click to edit, saves on blur/enter. */
function ProducedCell({ so, item, editable }: { so: SoDetail; item: SoItem; editable: boolean }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (qty: string) => salesApi.setProduced(so.id, item.id, qty),
    meta: { silent: true },
    onSuccess: (res) => {
      queryClient.setQueryData([SALES.orders, 'detail', so.id], res);
      setValue(null);
    },
    onError: (error) => {
      notifyError(error, 'Could not save produced qty');
      setValue(null);
    },
  });
  if (!editable) return <QtyText value={item.qty_produced} />;
  const save = () => {
    if (value !== null && compare(value, item.qty_produced) !== 0) mutation.mutate(value || '0');
    else setValue(null);
  };
  return (
    <InputNumber<string>
      stringMode
      size="small"
      min="0"
      max={item.qty_ordered}
      precision={3}
      value={value ?? item.qty_produced}
      onChange={(v) => setValue(v ?? '0')}
      onBlur={save}
      onPressEnter={save}
      disabled={mutation.isPending}
      style={{ width: 110 }}
      aria-label={`Produced ${item.product_code}`}
    />
  );
}

// --- Deliver dialog --------------------------------------------------------------------------

interface DeliverRow {
  item: SoItem;
  qty: string | null;
}

function deliverable(item: SoItem): string {
  // remaining, capped by what can actually leave now (own reservation + free stock)
  const canShip = sum([item.qty_reserved, item.qty_available ?? '0'], 3);
  return compare(canShip, item.qty_remaining) < 0 ? canShip : item.qty_remaining;
}

function DeliverModal({ so, open, onClose }: { so: SoDetail; open: boolean; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const canInvoice = usePermission('invoice.create');
  const [rows, setRows] = useState<DeliverRow[]>([]);
  const [form] = Form.useForm<{ delivery_date: Dayjs; notes: string; create_invoice: boolean }>();

  const chosen = rows.filter((r) => r.qty && compare(r.qty, 0) > 0);
  const over = rows.some((r) => r.qty && compare(r.qty, r.item.qty_remaining) > 0);
  const value = sum(chosen.map((r) => multiply(r.qty, r.item.unit_price, 2)), 2);

  const mutation = useMutation({
    mutationFn: (v: { delivery_date: Dayjs; notes: string; create_invoice: boolean }) =>
      salesApi.deliver(so.id, {
        delivery_date: v.delivery_date.format('YYYY-MM-DD'),
        notes: v.notes ?? '',
        create_invoice: v.create_invoice,
        items: chosen.map((r) => ({ so_item_id: r.item.id, qty: r.qty! })),
      }),
    meta: { silent: true },
    onSuccess: async (dlv) => {
      message.success(dlv.inv_number ? `${dlv.dlv_number} delivered and invoiced as ${dlv.inv_number}` : `${dlv.dlv_number} delivered`);
      onClose();
      await Promise.all(SALES_INVALIDATES.map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
    },
    onError: (error) => applyServerErrors(form, error),
  });

  return (
    <Modal
      title={`Deliver: ${so.so_number}`}
      open={open}
      width={960}
      onCancel={onClose}
      afterOpenChange={(visible) => {
        if (visible) {
          setRows(so.items.filter((i) => compare(i.qty_remaining, 0) > 0).map((item) => ({ item, qty: deliverable(item) })));
          form.resetFields();
          mutation.reset();
        }
      }}
      okText="Deliver"
      okButtonProps={{ disabled: !chosen.length || over }}
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      {mutation.isError && <Alert type="error" showIcon title="Could not deliver" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />}
      <Typography.Paragraph type="secondary">
        From <strong>{so.warehouse_name}</strong>. Reserved stock is used first; the rest must be free stock. Quantities are pre-filled with what
        can leave now.
      </Typography.Paragraph>
      <Table<DeliverRow>
        rowKey={(r) => r.item.id}
        size="small"
        pagination={false}
        dataSource={rows}
        columns={[
          { title: 'Product', key: 'p', render: (_, r) => <>{r.item.product_code} {r.item.product_name}</> },
          { title: right('Remaining'), key: 'rem', render: (_, r) => <QtyText value={r.item.qty_remaining} unit={r.item.unit_code} /> },
          { title: right('Reserved'), key: 'res', render: (_, r) => <QtyText value={r.item.qty_reserved} /> },
          { title: right('Free stock'), key: 'av', render: (_, r) => <QtyText value={r.item.qty_available} /> },
          {
            title: 'Deliver now',
            key: 'qty',
            width: 150,
            render: (_, r) => {
              const short = r.qty && compare(r.qty, sum([r.item.qty_reserved, r.item.qty_available ?? '0'], 3)) > 0;
              const tooMany = r.qty && compare(r.qty, r.item.qty_remaining) > 0;
              return (
                <InputNumber<string>
                  stringMode
                  min="0"
                  precision={3}
                  value={r.qty}
                  status={tooMany ? 'error' : short ? 'warning' : undefined}
                  onChange={(qty) => setRows((prev) => prev.map((x) => (x.item.id === r.item.id ? { ...x, qty } : x)))}
                  style={{ width: '100%' }}
                  aria-label={`Deliver qty ${r.item.product_code}`}
                />
              );
            },
          },
          { title: right('Amount'), key: 'amt', render: (_, r) => <MoneyText value={multiply(r.qty, r.item.unit_price, 2)} /> },
        ]}
      />
      <Form
        form={form}
        layout="inline"
        initialValues={{ delivery_date: dayjs(), notes: '', create_invoice: canInvoice }}
        onFinish={(v) => mutation.mutate(v)}
        style={{ marginTop: 16, rowGap: 8 }}
      >
        <Form.Item name="delivery_date" label="Delivery date" rules={[{ required: true }]}>
          <DatePicker allowClear={false} />
        </Form.Item>
        <Form.Item name="create_invoice" label="Create invoice" valuePropName="checked">
          <Switch disabled={!canInvoice} />
        </Form.Item>
        <Form.Item name="notes" label="Notes" style={{ flex: 1, minWidth: 220 }}>
          <Input placeholder="e.g. vehicle / challan no." />
        </Form.Item>
      </Form>
      <Flex justify="flex-end" style={{ marginTop: 12 }}>
        <Typography.Text>
          Value: <strong>{formatDecimal(value, 2)}</strong>
          {compare(so.discount, 0) > 0 && <Typography.Text type="secondary"> (the invoice gets its share of the {formatDecimal(so.discount, 2)} discount)</Typography.Text>}
        </Typography.Text>
      </Flex>
    </Modal>
  );
}

function ReserveResult({ lines, onClose }: { lines: ReserveLine[] | null; onClose: () => void }) {
  const short = (lines ?? []).filter((l) => compare(l.short, 0) > 0);
  return (
    <Modal title="Reservation result" open={lines !== null} onCancel={onClose} onOk={onClose} cancelButtonProps={{ style: { display: 'none' } }} width={720}>
      {short.length ? (
        <Alert type="warning" showIcon title={`Partial reservation: ${short.length} line(s) are short of stock.`} style={{ marginBottom: 12 }} />
      ) : (
        <Alert type="success" showIcon title="Everything still to deliver is reserved." style={{ marginBottom: 12 }} />
      )}
      <Table<ReserveLine>
        rowKey="so_item_id"
        size="small"
        pagination={false}
        dataSource={lines ?? []}
        columns={[
          { title: 'Product', key: 'p', render: (_, l) => <>{l.product_code} {l.product_name}</> },
          { title: right('Needed'), dataIndex: 'wanted', render: (v: string) => <QtyText value={v} /> },
          { title: right('Reserved now'), dataIndex: 'reserved_now', render: (v: string) => <QtyText value={v} /> },
          { title: right('Reserved total'), dataIndex: 'reserved_total', render: (v: string) => <QtyText value={v} /> },
          {
            title: right('Short'),
            dataIndex: 'short',
            render: (v: string) =>
              compare(v, 0) > 0 ? <Typography.Text type="danger" style={{ display: 'block', textAlign: 'right' }}>{formatDecimal(v, 3, true)}</Typography.Text> : <QtyText value={v} />,
          },
        ]}
      />
    </Modal>
  );
}

// --- Page ------------------------------------------------------------------------------------

export default function SalesOrderPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const canEdit = usePermission('sales_order.edit');
  const canCancel = usePermission('sales_order.delete');
  const canReserve = usePermission('reservation.manage');
  const canDeliver = usePermission('delivery.create');
  const canInvoice = usePermission('invoice.create');
  const [delivering, setDelivering] = useState(false);
  const [reserved, setReserved] = useState<ReserveLine[] | null>(null);

  const so = useQuery({
    queryKey: [SALES.orders, 'detail', id],
    queryFn: () => salesApi.order(id),
    enabled: Number.isInteger(id),
  });

  const refresh = (result?: SoDetail) => {
    if (result) queryClient.setQueryData([SALES.orders, 'detail', id], result);
    return Promise.all(SALES_INVALIDATES.map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
  };

  const action = useMutation({
    mutationFn: (what: 'confirm' | 'cancel' | 'release') => salesApi.orderAction(id, what),
    meta: { silent: true },
    onSuccess: async (result, what) => {
      message.success({ confirm: `${result.so_number} confirmed`, cancel: `${result.so_number} cancelled`, release: 'Reservation released' }[what]);
      await refresh(result);
    },
  });
  const reserve = useMutation({
    mutationFn: () => salesApi.reserve(id),
    meta: { silent: true },
    onSuccess: async (result) => {
      setReserved(result.lines);
      await refresh(result.order);
    },
  });
  const invoiceDelivery = useMutation({
    mutationFn: (dlv: DeliveryDoc) => salesApi.invoiceDelivery(dlv.id),
    meta: { silent: true },
    onSuccess: async (inv) => {
      message.success(`${inv.inv_number} created for ${inv.dlv_number}`);
      await refresh();
    },
  });
  const failed = [action, reserve, invoiceDelivery].find((m) => m.isError);

  if (so.isError) return <ErrorState error={so.error} onRetry={() => so.refetch()} />;
  if (!so.data) return <Skeleton active />;
  const d = so.data;
  const isOpen = OPEN.includes(d.status);
  const hasReserved = d.items.some((i) => compare(i.qty_reserved, 0) > 0);
  const needsReserve = d.items.some((i) => compare(i.qty_remaining, i.qty_reserved) > 0);
  const nothingDelivered = d.items.every((i) => compare(i.qty_delivered, 0) === 0);

  const columns: TableProps<SoItem>['columns'] = [
    {
      title: 'Product',
      key: 'p',
      render: (_, i) => (
        <Link to={`/inventory/ledger?product_id=${i.product_id}&warehouse_id=${d.warehouse_id}`}>
          <Typography.Text code>{i.product_code}</Typography.Text> {i.product_name}
        </Link>
      ),
    },
    { title: right('Ordered'), dataIndex: 'qty_ordered', render: (v: string, i) => <QtyText value={v} unit={i.unit_code} /> },
    {
      title: right('Available'),
      dataIndex: 'qty_available',
      render: (v: string | null, i) => {
        const needed = compare(i.qty_remaining, i.qty_reserved) > 0 && compare(v ?? '0', 0) <= 0;
        return <span style={{ color: needed ? 'var(--ant-color-error, #ff4d4f)' : undefined }}><QtyText value={v} /></span>;
      },
    },
    { title: right('Reserved'), dataIndex: 'qty_reserved', render: (v: string) => <QtyText value={v} /> },
    { title: 'Produced', key: 'produced', width: 130, render: (_, i) => <ProducedCell so={d} item={i} editable={canEdit && d.status !== 'cancelled' && d.status !== 'delivered'} /> },
    { title: right('Delivered'), dataIndex: 'qty_delivered', render: (v: string) => <QtyText value={v} /> },
    {
      title: right('Remaining'),
      dataIndex: 'qty_remaining',
      render: (v: string) =>
        compare(v, 0) > 0 ? <strong><QtyText value={v} /></strong> : <Typography.Text type="success" style={{ display: 'block', textAlign: 'right' }}>✓</Typography.Text>,
    },
    { title: right('Price'), dataIndex: 'unit_price', render: (v: string) => <MoneyText value={v} /> },
    { title: right('Amount'), dataIndex: 'line_total', render: (v: string) => <MoneyText value={v} /> },
  ];

  return (
    <>
      <PageHeader
        title={<Flex gap={12} align="center">Sales Order {d.so_number} <StatusTag status={d.status} /></Flex>}
        actions={
          <>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(SALES.orders)}>Orders</Button>
            {canCancel && nothingDelivered && ['draft', 'confirmed'].includes(d.status) && (
              <ConfirmButton icon={<CloseOutlined />} danger confirm={`Cancel ${d.so_number}?`} description={hasReserved ? 'Its reserved stock will be released.' : undefined}
                okText="Cancel order" loading={action.isPending && action.variables === 'cancel'} onConfirm={() => action.mutateAsync('cancel')}>
                Cancel
              </ConfirmButton>
            )}
            {canEdit && d.status === 'draft' && (
              <ConfirmButton type="primary" icon={<CheckOutlined />} confirm={`Confirm ${d.so_number}?`} description="Confirmed orders can be reserved and delivered but no longer edited."
                okText="Confirm" loading={action.isPending && action.variables === 'confirm'} onConfirm={() => action.mutateAsync('confirm')}>
                Confirm
              </ConfirmButton>
            )}
            {canReserve && isOpen && hasReserved && (
              <ConfirmButton icon={<UnlockOutlined />} confirm="Release all reserved stock of this order?" okText="Release"
                loading={action.isPending && action.variables === 'release'} onConfirm={() => action.mutateAsync('release')}>
                Release
              </ConfirmButton>
            )}
            {canReserve && isOpen && needsReserve && (
              <Button icon={<LockOutlined />} loading={reserve.isPending} onClick={() => reserve.mutate()}>
                Reserve
              </Button>
            )}
            {canDeliver && isOpen && (
              <Button type="primary" icon={<CarOutlined />} onClick={() => setDelivering(true)}>
                Deliver
              </Button>
            )}
          </>
        }
      />
      {failed && (
        <Alert type="error" showIcon closable={{ onClose: () => failed.reset() }} title="Action failed" description={errorMessage(failed.error)} style={{ marginBottom: 16 }} />
      )}
      {d.status === 'draft' && <Alert type="info" showIcon title="Draft: edit it from the order list, then confirm it to reserve and deliver." style={{ marginBottom: 16 }} />}
      <StatusSteps so={d} />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={17}>
          <Card size="small">
            <Descriptions
              size="small"
              column={{ xs: 1, md: 2 }}
              items={[
                { label: 'Customer', children: <>{d.customer_code} {d.customer_name}</> },
                { label: 'Deliver from', children: d.warehouse_name },
                { label: 'Order date', children: <DateText value={d.order_date} /> },
                { label: 'Delivery by', children: <DateText value={d.delivery_date} /> },
                { label: 'Created by', children: d.created_by_name },
                { label: 'Confirmed by', children: d.confirmed_by_name ?? '—' },
                ...(d.quotation_number ? [{ label: 'From quotation', children: d.quotation_number }] : []),
                ...(d.notes ? [{ label: 'Notes', children: d.notes, span: 'filled' as const }] : []),
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={7}>
          <Card size="small">
            <Statistic title="Customer current due" value={formatDecimal(d.customer_due, 2)} />
          </Card>
        </Col>
      </Row>

      <Table<SoItem>
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
              ...(compare(d.discount, 0) > 0 ? [['Discount', `-${d.discount}`]] : []),
              ['Order total', d.total],
            ].map(([label, value], i, all) => (
              <Table.Summary.Row key={label}>
                <Table.Summary.Cell index={0} colSpan={8} align="right">
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

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={24} xl={12}>
          <Typography.Title level={5}>Deliveries</Typography.Title>
          {d.deliveries.length === 0 ? (
            <Empty description="Nothing delivered yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table<DeliveryDoc>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={d.deliveries}
              columns={[
                { title: 'Delivery', dataIndex: 'dlv_number', render: (v: string) => <strong>{v}</strong> },
                { title: 'Date', dataIndex: 'delivery_date', render: (v: string) => <DateText value={v} /> },
                {
                  title: 'Items',
                  key: 'items',
                  render: (_, dlv) => dlv.items.map((i) => `${formatDecimal(i.qty, 3, true)} ${i.unit_code} ${i.product_code}`).join(', '),
                },
                {
                  title: 'Invoice',
                  key: 'inv',
                  render: (_, dlv) =>
                    dlv.invoice_id ? (
                      <Link to={`${SALES.invoices}/${dlv.invoice_id}`}>{dlv.inv_number}</Link>
                    ) : canInvoice ? (
                      <ConfirmButton size="small" icon={<FileDoneOutlined />} confirm={`Invoice ${dlv.dlv_number}?`} description="Posts the customer due for this delivery."
                        loading={invoiceDelivery.isPending && invoiceDelivery.variables?.id === dlv.id} onConfirm={() => invoiceDelivery.mutateAsync(dlv)}>
                        Create invoice
                      </ConfirmButton>
                    ) : (
                      <Typography.Text type="secondary">Not invoiced</Typography.Text>
                    ),
                },
              ]}
            />
          )}
        </Col>
        <Col xs={24} xl={12}>
          <Typography.Title level={5}>Invoices</Typography.Title>
          {d.invoices.length === 0 ? (
            <Empty description="No invoices yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Table<Invoice>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={d.invoices}
              columns={[
                { title: 'Invoice', key: 'n', render: (_, inv) => <Link to={`${SALES.invoices}/${inv.id}`}><strong>{inv.inv_number}</strong></Link> },
                { title: 'Date', dataIndex: 'invoice_date', render: (v: string) => <DateText value={v} /> },
                { title: right('Total'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} /> },
                { title: right('Outstanding'), dataIndex: 'outstanding', render: (v: string) => <MoneyText value={v} /> },
                { title: 'Status', dataIndex: 'status', render: (s: string) => <StatusTag status={s} /> },
              ]}
            />
          )}
        </Col>
      </Row>

      <DeliverModal so={d} open={delivering} onClose={() => setDelivering(false)} />
      <ReserveResult lines={reserved} onClose={() => setReserved(null)} />
    </>
  );
}
