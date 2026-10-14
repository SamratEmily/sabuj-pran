import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Col, DatePicker, Descriptions, Form, Input, InputNumber, Modal, Row, Select, Table, Typography } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';

import { errorMessage } from '../../api/client';
import { useLookups } from '../../api/master';
import { useAccountBalance } from '../../api/money';
import { SALES_INVALIDATES, salesApi } from '../../api/sales';
import type { InvoiceDetail, InvoiceItem } from '../../api/sales';
import MoneyText from '../../components/MoneyText';
import QtyText from '../../components/QtyText';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { compare, formatDecimal, multiply, ratio, subtract, sum } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

interface Row {
  item: InvoiceItem;
  qty: string | null;
}

interface FormValues {
  return_date: Dayjs;
  refund_amount?: string | null;
  refund_account_id?: number | null;
  notes?: string;
}

function AccountBalance({ id }: { id?: number | null }) {
  const canView = usePermission('money_account.view');
  const account = useAccountBalance(id ?? undefined, canView);
  if (!canView || !account.data) return null;
  return <Typography.Text type="secondary">Balance: {formatDecimal(account.data.balance, 2)}</Typography.Text>;
}

/** Return goods from an invoice: stock back at the original COGS, customer credit, and an
 *  optional cash refund. */
export default function SalesReturnModal({ invoice, onClose }: { invoice: InvoiceDetail | null; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const lookups = useLookups();
  const [rows, setRows] = useState<Row[]>([]);
  const [form] = Form.useForm<FormValues>();

  const chosen = rows.filter((r) => r.qty && compare(r.qty, 0) > 0);
  const over = rows.some((r) => r.qty && compare(r.qty, r.item.qty_returnable) > 0);
  const gross = sum(chosen.map((r) => multiply(r.qty, r.item.unit_price, 2)), 2);
  // Estimate of this return's discount share (the server computes the exact figure).
  const discountShare =
    invoice && compare(invoice.discount, 0) > 0 && compare(invoice.subtotal, 0) > 0
      ? ratio(gross, invoice.discount, invoice.subtotal, 2)
      : '0';
  const net = subtract(gross, discountShare, 2);
  // Only what the customer has overpaid after this return can be refunded (server rule):
  // min(net, net - outstanding), never below 0. An unpaid invoice gets no refund.
  const outstanding = invoice?.outstanding ?? '0';
  const afterReturn = subtract(net, compare(outstanding, 0) > 0 ? outstanding : '0', 2);
  const refundable = compare(afterReturn, 0) > 0 ? afterReturn : '0.00';

  const mutation = useMutation({
    mutationFn: (v: FormValues) =>
      salesApi.returnGoods(invoice!.id, {
        return_date: v.return_date.format('YYYY-MM-DD'),
        refund_amount: v.refund_amount || '0',
        refund_account_id: v.refund_amount && compare(v.refund_amount, 0) > 0 ? (v.refund_account_id ?? null) : null,
        notes: v.notes ?? '',
        items: chosen.map((r) => ({ invoice_item_id: r.item.id, qty: r.qty! })),
      }),
    meta: { silent: true },
    onSuccess: async (ret) => {
      message.success(
        `${ret.srn_number}: ${formatDecimal(ret.total, 2)} credited to the customer` +
          (compare(ret.refund_amount, 0) > 0 ? `, ${formatDecimal(ret.refund_amount, 2)} refunded` : ''),
      );
      onClose();
      await Promise.all(SALES_INVALIDATES.map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
    },
    onError: (error) =>
      applyServerErrors(form, error, {
        INSUFFICIENT_FUNDS: 'refund_amount',
        INVALID_REFUND: 'refund_amount',
        ACCOUNT_REQUIRED: 'refund_account_id',
        INACTIVE_ACCOUNT: 'refund_account_id',
      }),
  });

  return (
    <Modal
      title={invoice ? `Sales return: ${invoice.inv_number}` : ''}
      open={invoice !== null}
      width={900}
      onCancel={onClose}
      afterOpenChange={(open) => {
        if (open && invoice) {
          setRows(invoice.items.filter((i) => compare(i.qty_returnable, 0) > 0).map((item) => ({ item, qty: null })));
          form.resetFields();
          mutation.reset();
        }
      }}
      okText="Post return"
      okButtonProps={{ danger: true, disabled: !chosen.length || over }}
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      {mutation.isError && <Alert type="error" showIcon title="Could not post the return" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />}
      {invoice && (
        <>
          <Typography.Paragraph type="secondary">
            Goods go back into <strong>{invoice.warehouse_name}</strong> at the cost they left with. {invoice.customer_name} is credited the
            net value{compare(invoice.discount, 0) > 0 ? ' (after the invoice discount share)' : ''}.
          </Typography.Paragraph>
          <Table<Row>
            rowKey={(r) => r.item.id}
            size="small"
            pagination={false}
            dataSource={rows}
            locale={{ emptyText: 'Everything on this invoice has been returned' }}
            columns={[
              { title: 'Product', key: 'p', render: (_, r) => <>{r.item.product_code} {r.item.product_name}</> },
              { title: right('Invoiced'), key: 'q', render: (_, r) => <QtyText value={r.item.qty} unit={r.item.unit_code} /> },
              { title: right('Returnable'), key: 'rt', render: (_, r) => <QtyText value={r.item.qty_returnable} /> },
              { title: right('Price'), key: 'pr', render: (_, r) => <MoneyText value={r.item.unit_price} /> },
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
                    status={r.qty && compare(r.qty, r.item.qty_returnable) > 0 ? 'error' : undefined}
                    onChange={(qty) => setRows((prev) => prev.map((x) => (x.item.id === r.item.id ? { ...x, qty } : x)))}
                    style={{ width: '100%' }}
                    aria-label={`Return qty ${r.item.product_code}`}
                  />
                ),
              },
              { title: right('Amount'), key: 'a', render: (_, r) => <MoneyText value={multiply(r.qty, r.item.unit_price, 2)} /> },
            ]}
          />
          <Form<FormValues>
            form={form}
            layout="vertical"
            initialValues={{ return_date: dayjs(), refund_amount: null, notes: '' }}
            onFinish={(v) => mutation.mutate(v)}
            style={{ marginTop: 16 }}
          >
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item name="return_date" label="Return date" rules={[{ required: true }]}>
                  <DatePicker allowClear={false} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="refund_amount"
                  label="Refund now (optional)"
                  extra={`Up to ${formatDecimal(refundable, 2)}: what the customer has paid beyond what they owe after this return`}
                  rules={[
                    {
                      validator: (_, v) =>
                        v && compare(v, refundable) > 0
                          ? Promise.reject(new Error(`Refund cannot exceed ${formatDecimal(refundable, 2)}`))
                          : Promise.resolve(),
                    },
                  ]}
                >
                  <InputNumber<string>
                    stringMode
                    min="0"
                    precision={2}
                    disabled={compare(refundable, 0) <= 0}
                    style={{ width: '100%' }}
                    placeholder="0.00"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item noStyle dependencies={['refund_amount', 'refund_account_id']}>
                  {({ getFieldValue }) => {
                    const refund = getFieldValue('refund_amount');
                    const refunding = !!refund && compare(refund, 0) > 0;
                    return (
                      <Form.Item
                        name="refund_account_id"
                        label="Refund from"
                        rules={[{ required: refunding, message: 'Choose the account' }]}
                        extra={<AccountBalance id={getFieldValue('refund_account_id')} />}
                      >
                        <Select allowClear disabled={!refunding} options={(lookups.data?.money_accounts ?? []).map((a) => ({ label: a.name, value: a.id }))} />
                      </Form.Item>
                    );
                  }}
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="notes" label="Reason / notes" rules={[{ max: 1000 }]}>
              <Input placeholder="e.g. damaged, wrong item" />
            </Form.Item>
          </Form>
          <Descriptions
            size="small"
            column={3}
            items={[
              { label: 'Gross', children: formatDecimal(gross, 2) },
              { label: 'Discount share (est.)', children: formatDecimal(discountShare, 2) },
              { label: <strong>Customer credit</strong>, children: <strong>{formatDecimal(net, 2)}</strong> },
            ]}
          />
        </>
      )}
    </Modal>
  );
}
