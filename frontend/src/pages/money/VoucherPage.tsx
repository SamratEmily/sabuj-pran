import { RollbackOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Col, DatePicker, Form, Input, InputNumber, Modal, Row, Select, Tooltip, Typography } from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { errorMessage } from '../../api/client';
import { useLookups } from '../../api/master';
import { MONEY, moneyApi, useAccountBalance } from '../../api/money';
import type { VoucherRecord } from '../../api/money';
import type { PartyRecord } from '../../api/parties';
import { SALES } from '../../api/sales';
import type { Invoice } from '../../api/sales';
import CrudPage from '../../components/CrudPage';
import PartyDue from '../../components/PartyDue';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import StatusTag from '../../components/StatusTag';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { compare, formatDecimal } from '../../utils/decimal';

type VoucherKind = 'collections' | 'supplierPayments' | 'expenses' | 'incomes' | 'transfers';

interface Config {
  title: string;
  endpoint: string;
  permission: string;
  itemName: string;
  dateField: string;
  direction: 'in' | 'out' | 'transfer';
  party?: 'customers' | 'suppliers';
  category?: 'expense_categories' | 'income_categories';
}

const CONFIG: Record<VoucherKind, Config> = {
  collections: { title: 'Customer Collections', endpoint: MONEY.collections, permission: 'collection', itemName: 'collection', dateField: 'collection_date', direction: 'in', party: 'customers' },
  supplierPayments: { title: 'Supplier Payments', endpoint: MONEY.supplierPayments, permission: 'supplier_payment', itemName: 'payment', dateField: 'payment_date', direction: 'out', party: 'suppliers' },
  expenses: { title: 'Expenses', endpoint: MONEY.expenses, permission: 'expense', itemName: 'expense', dateField: 'expense_date', direction: 'out', category: 'expense_categories' },
  incomes: { title: 'Other Income', endpoint: MONEY.incomes, permission: 'income', itemName: 'income', dateField: 'income_date', direction: 'in', category: 'income_categories' },
  transfers: { title: 'Fund Transfers', endpoint: MONEY.transfers, permission: 'money_transfer', itemName: 'transfer', dateField: 'transfer_date', direction: 'transfer' },
};

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

/** Optional invoice for a collection: the customer's invoices with something outstanding.
 *  Users who can't view invoices only see the one passed in from a link. */
function InvoicePicker({ id, customerId, value, onChange }: { id?: string; customerId?: number; value?: number | null; onChange?: (v: number | null) => void }) {
  const canView = usePermission('invoice.view');
  const invoices = useList<Invoice>(SALES.invoices, { customer_id: customerId, page_size: 100 }, canView && !!customerId);
  if (!canView) return value ? <Typography.Text>Invoice #{value}</Typography.Text> : <Typography.Text type="secondary">None</Typography.Text>;
  const options = (invoices.data?.items ?? [])
    .filter((i) => compare(i.outstanding, 0) > 0 || i.id === value)
    .map((i) => ({ value: i.id, label: `${i.inv_number} · outstanding ${formatDecimal(i.outstanding, 2)}`, outstanding: i.outstanding }));
  return (
    <Select
      id={id}
      allowClear
      value={value ?? undefined}
      onChange={(v?: number) => onChange?.(v ?? null)}
      options={options}
      loading={invoices.isPending && !!customerId}
      disabled={!customerId}
      placeholder={customerId ? (options.length ? 'Not linked to an invoice' : 'No open invoices') : 'Choose the customer first'}
      notFoundContent="No open invoices"
    />
  );
}

/** Balance hint under an account picker, for users who may see account balances. */
function BalanceHint({ id }: { id?: number }) {
  const canView = usePermission('money_account.view');
  const account = useAccountBalance(id, canView);
  if (!canView || !account.data) return null;
  return <Typography.Text type="secondary">Balance: {formatDecimal(account.data.balance, 2)}</Typography.Text>;
}

function ReverseButton({ cfg, voucher }: { cfg: Config; voucher: VoucherRecord }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const mutation = useMutation({
    mutationFn: () => moneyApi.reverse(cfg.endpoint, voucher.id, reason),
    meta: { silent: true },
    onSuccess: async () => {
      message.success(`${voucher.number} reversed`);
      setOpen(false);
      await Promise.all(
        [cfg.endpoint, MONEY.accounts, '/customers', '/suppliers'].map((k) => queryClient.invalidateQueries({ queryKey: [k] })),
      );
    },
  });
  return (
    <>
      <Tooltip title="Reverse">
        <Button size="small" type="text" danger icon={<RollbackOutlined />} aria-label="Reverse" onClick={() => { setReason(''); mutation.reset(); setOpen(true); }} />
      </Tooltip>
      <Modal
        title={`Reverse ${voucher.number}?`}
        open={open}
        onCancel={() => setOpen(false)}
        okText="Reverse"
        okButtonProps={{ danger: true }}
        confirmLoading={mutation.isPending}
        onOk={() => mutation.mutate()}
        destroyOnHidden
      >
        {mutation.isError && <Alert type="error" showIcon title="Could not reverse" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />}
        <Typography.Paragraph>
          Opposite entries will undo the {formatDecimal(voucher.amount, 2)} in the account
          {voucher.party_name ? ` and ${voucher.party_name}'s balance` : ''}. The voucher stays, marked reversed.
        </Typography.Paragraph>
        <Input.TextArea placeholder="Reason (optional)" value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </>
  );
}

export default function VoucherPage({ kind }: { kind: VoucherKind }) {
  const cfg = CONFIG[kind];
  const { message } = App.useApp();
  const lookups = useLookups();
  const canReverse = usePermission(`${cfg.permission}.delete`);
  const parties = useList<PartyRecord>(cfg.party ? `/${cfg.party}` : '/none', { page_size: 100, is_active: true }, !!cfg.party);
  const partyOptions = (parties.data?.items ?? []).map((p) => ({ label: `${p.code} ${p.name}`, value: p.id }));
  const accounts = (lookups.data?.money_accounts ?? []).map((a) => ({ label: a.name, value: a.id }));
  const categories = cfg.category ? (lookups.data?.[cfg.category] ?? []).map((c) => ({ label: c.name, value: c.id })) : [];
  const partyField = cfg.party === 'customers' ? 'customer_id' : 'supplier_id';
  const categoryField = cfg.category === 'expense_categories' ? 'expense_category_id' : 'income_category_id';
  // "Collect payment" on an invoice links here with ?customer_id=&invoice_id=&amount=
  const [params] = useSearchParams();
  const openWith = useMemo(() => {
    const customer = Number(params.get('customer_id'));
    if (kind !== 'collections' || !customer) return null;
    const invoice = Number(params.get('invoice_id'));
    return { customer_id: customer, invoice_id: invoice || null, amount: params.get('amount') ?? undefined };
  }, [kind, params]);

  const columns: TableProps<VoucherRecord>['columns'] = [
    { title: 'Number', dataIndex: 'number', render: (v: string) => <strong>{v}</strong> },
    { title: 'Date', dataIndex: 'voucher_date', render: (v: string) => <DateText value={v} /> },
    ...(cfg.party ? [{ title: cfg.party === 'customers' ? 'Customer' : 'Supplier', key: 'party', render: (_: unknown, v: VoucherRecord) => <>{v.party_code} {v.party_name}</> }] : []),
    ...(cfg.category ? [{ title: 'Category', dataIndex: 'category_name' }] : []),
    ...(kind === 'expenses' ? [{ title: 'Paid to', dataIndex: 'paid_to', render: (v: string) => v || '—' }] : []),
    ...(cfg.direction === 'transfer'
      ? [{ title: 'From → To', key: 'ft', render: (_: unknown, v: VoucherRecord) => <>{v.from_account_name} → {v.to_account_name}</> }]
      : [{ title: cfg.direction === 'in' ? 'Into account' : 'From account', dataIndex: 'account_name' }]),
    ...(cfg.party ? [{ title: 'Reference', dataIndex: 'reference_no', render: (v: string) => v || '—' }] : []),
    ...(kind === 'collections'
      ? [{ title: 'Invoice', key: 'inv', render: (_: unknown, v: VoucherRecord) => (v.invoice_id ? <Link to={`${SALES.invoices}/${v.invoice_id}`}>{v.invoice_number}</Link> : '—') }]
      : []),
    { title: right('Amount'), dataIndex: 'amount', render: (v: string) => <MoneyText value={v} strong /> },
    {
      title: 'Status',
      key: 'status',
      render: (_, v) => (
        <Tooltip title={v.status === 'reversed' ? `By ${v.reversed_by_name}${v.reversal_reason ? `: ${v.reversal_reason}` : ''}` : undefined}>
          <span><StatusTag status={v.status} /></span>
        </Tooltip>
      ),
    },
    { title: 'By', dataIndex: 'created_by_name' },
  ];

  return (
    <CrudPage<VoucherRecord, Record<string, unknown>>
      key={kind}
      title={cfg.title}
      endpoint={cfg.endpoint}
      permission={cfg.permission}
      itemName={cfg.itemName}
      searchPlaceholder={cfg.party ? 'Number or reference' : kind === 'expenses' ? 'Number or paid to' : 'Number'}
      editable={false}
      deactivatable={false}
      dateRangeFilter
      saveLabel="Post"
      formMode="modal"
      formWidth={600}
      invalidates={[MONEY.accounts, '/customers', '/suppliers', SALES.invoices]}
      openWith={openWith}
      initialSearch={params.get('search') ?? ''}
      onSaved={(v) => {
        if (v.status === 'pending_approval') message.warning(`${v.number} needs approval: nothing is posted until it is approved`);
      }}
      filters={[
        ...(cfg.party ? [{ name: 'party_id', label: cfg.party === 'customers' ? 'Customer' : 'Supplier', options: partyOptions, width: 220 }] : []),
        ...(cfg.category ? [{ name: 'category_id', label: 'Category', options: categories }] : []),
        { name: 'account_id', label: 'Account', options: accounts },
        {
          name: 'status',
          label: 'Status',
          options: [
            { label: 'Posted', value: 'posted' },
            { label: 'Reversed', value: 'reversed' },
            ...(kind === 'expenses' || kind === 'supplierPayments'
              ? [
                  { label: 'Pending approval', value: 'pending_approval' },
                  { label: 'Rejected', value: 'rejected' },
                ]
              : []),
          ],
        },
      ]}
      initialValues={{ [cfg.dateField]: dayjs() }}
      errorFields={{
        INSUFFICIENT_FUNDS: cfg.direction === 'transfer' ? 'from_account_id' : 'amount',
        INACTIVE_ACCOUNT: 'account_id',
        SAME_ACCOUNT: 'to_account_id',
        INVALID_CUSTOMER: 'customer_id',
        INVALID_SUPPLIER: 'supplier_id',
        INVALID_CATEGORY: categoryField,
        OVERPAYMENT: 'amount',
        INVALID_INVOICE: 'invoice_id',
        INVOICE_NOT_FOUND: 'invoice_id',
      }}
      toPayload={(v) => ({ ...v, [cfg.dateField]: (v[cfg.dateField] as Dayjs).format('YYYY-MM-DD') })}
      rowActions={(v) => canReverse && v.status === 'posted' && <ReverseButton cfg={cfg} voucher={v} />}
      columns={columns}
      renderForm={() => (
        <>
          {cfg.party && (
            <>
              <Form.Item name={partyField} label={cfg.party === 'customers' ? 'Customer' : 'Supplier'} rules={[{ required: true, message: cfg.party === 'customers' ? 'Choose a customer' : 'Choose a supplier' }]}>
                <Select showSearch={{ optionFilterProp: 'label' }} options={partyOptions} loading={parties.isPending} placeholder="Search by name or code" />
              </Form.Item>
              <Form.Item noStyle dependencies={[partyField]}>
                {({ getFieldValue }) => <PartyDue kind={cfg.party!} id={getFieldValue(partyField)} />}
              </Form.Item>
              {kind === 'collections' && (
                <Form.Item noStyle dependencies={[partyField]}>
                  {({ getFieldValue }) => (
                    <Form.Item name="invoice_id" label="Against invoice (optional)">
                      <InvoicePicker customerId={getFieldValue(partyField)} />
                    </Form.Item>
                  )}
                </Form.Item>
              )}
            </>
          )}
          {cfg.category && (
            <Form.Item name={categoryField} label="Category" rules={[{ required: true, message: 'Choose a category' }]}>
              <Select showSearch={{ optionFilterProp: 'label' }} options={categories} loading={lookups.isPending} />
            </Form.Item>
          )}
          {cfg.direction === 'transfer' ? (
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="from_account_id" label="From account" rules={[{ required: true, message: 'Choose the source' }]}>
                  <Select options={accounts} />
                </Form.Item>
                <Form.Item noStyle dependencies={['from_account_id']}>
                  {({ getFieldValue }) => <div style={{ marginTop: -16, marginBottom: 16 }}><BalanceHint id={getFieldValue('from_account_id')} /></div>}
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="to_account_id"
                  label="To account"
                  dependencies={['from_account_id']}
                  rules={[
                    { required: true, message: 'Choose the destination' },
                    ({ getFieldValue }) => ({
                      validator: (_, v) => (v && v === getFieldValue('from_account_id') ? Promise.reject(new Error('Choose a different account')) : Promise.resolve()),
                    }),
                  ]}
                >
                  <Select options={accounts} />
                </Form.Item>
              </Col>
            </Row>
          ) : (
            <>
              <Form.Item name="account_id" label={cfg.direction === 'in' ? 'Received into' : 'Paid from'} rules={[{ required: true, message: 'Choose an account' }]}>
                <Select options={accounts} loading={lookups.isPending} />
              </Form.Item>
              {cfg.direction === 'out' && (
                <Form.Item noStyle dependencies={['account_id']}>
                  {({ getFieldValue }) => <div style={{ marginTop: -16, marginBottom: 16 }}><BalanceHint id={getFieldValue('account_id')} /></div>}
                </Form.Item>
              )}
            </>
          )}
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="amount" label="Amount" rules={[{ required: true, message: 'Enter the amount' }]}>
                <InputNumber<string> stringMode min="0.01" precision={2} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name={cfg.dateField} label="Date" rules={[{ required: true }]}>
                <DatePicker allowClear={false} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          {cfg.party && (
            <Form.Item name="reference_no" label="Reference" rules={[{ max: 100 }]}>
              <Input placeholder="Cheque / transaction / money receipt no." />
            </Form.Item>
          )}
          {kind === 'expenses' && (
            <Form.Item name="paid_to" label="Paid to" rules={[{ max: 150 }]}>
              <Input />
            </Form.Item>
          )}
          <Form.Item name="notes" label="Notes" rules={[{ max: 1000 }]}>
            <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
          </Form.Item>
          {kind === 'collections' && (
            <Typography.Text type="secondary">
              Against an invoice, the amount can't exceed what is outstanding. Without one, more than the due is kept as an advance.
            </Typography.Text>
          )}
        </>
      )}
    />
  );
}

export const CollectionsPage = () => <VoucherPage kind="collections" />;
export const SupplierPaymentsPage = () => <VoucherPage kind="supplierPayments" />;
export const ExpensesPage = () => <VoucherPage kind="expenses" />;
export const IncomesPage = () => <VoucherPage kind="incomes" />;
export const MoneyTransfersPage = () => <VoucherPage kind="transfers" />;

