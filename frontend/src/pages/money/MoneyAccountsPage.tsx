import { useQuery } from '@tanstack/react-query';
import { Card, Col, Form, Input, InputNumber, Row, Select, Statistic, Tag, Typography } from 'antd';
import { Link } from 'react-router';

import { useLookups } from '../../api/master';
import { ACCOUNT_TYPE_COLORS, ACCOUNT_TYPE_LABELS, MONEY, moneyApi } from '../../api/money';
import type { AccountType, MoneyAccountRecord } from '../../api/money';
import CrudPage from '../../components/CrudPage';
import MoneyText from '../../components/MoneyText';
import { formatDecimal } from '../../utils/decimal';

interface AccountForm {
  name: string;
  account_type: AccountType;
  payment_method_id?: number | null;
  account_number?: string;
  opening_balance?: string;
}

const TYPE_OPTIONS = Object.entries(ACCOUNT_TYPE_LABELS).map(([value, label]) => ({ value, label }));

function PositionCards() {
  const position = useQuery({ queryKey: [MONEY.accounts, 'position'], queryFn: moneyApi.position });
  const items: [string, string | undefined][] = [
    ['Cash', position.data?.cash],
    ['Bank', position.data?.bank],
    ['Mobile (MFS)', position.data?.mfs],
    ['Total', position.data?.total],
  ];
  return (
    <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
      {items.map(([label, value]) => (
        <Col key={label} xs={12} md={6}>
          <Card size="small">
            <Statistic title={label} value={value ? formatDecimal(value, 2) : '…'} styles={label === 'Total' ? { content: { fontWeight: 600 } } : undefined} />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

export default function MoneyAccountsPage() {
  const lookups = useLookups();
  const methods = (lookups.data?.payment_methods ?? []).map((m) => ({ label: m.name, value: m.id }));

  return (
    <CrudPage<MoneyAccountRecord, AccountForm>
      title="Money Accounts"
      endpoint={MONEY.accounts}
      permission="money_account"
      itemName="account"
      searchPlaceholder="Search name or account number"
      formMode="modal"
      headerExtra={<PositionCards />}
      invalidates={['/master/lookups']}
      filters={[{ name: 'account_type', label: 'Type', options: TYPE_OPTIONS }]}
      initialValues={{ account_type: 'cash', opening_balance: '0', account_number: '' }}
      errorFields={{ NAME_TAKEN: 'name', INVALID_PAYMENT_METHOD: 'payment_method_id' }}
      toFormValues={(a) => ({
        name: a.name,
        account_type: a.account_type,
        payment_method_id: a.payment_method_id,
        account_number: a.account_number,
      })}
      toPayload={(v, record) => {
        const base = {
          name: v.name,
          account_type: v.account_type,
          payment_method_id: v.payment_method_id ?? null,
          account_number: v.account_number ?? '',
        };
        return record ? base : { ...base, opening_balance: v.opening_balance || '0' };
      }}
      columns={[
        {
          title: 'Account',
          key: 'name',
          render: (_, a) => (
            <Link to={`/money/ledger?account_id=${a.id}`} title="Open account ledger">
              <strong>{a.name}</strong>
            </Link>
          ),
        },
        { title: 'Type', dataIndex: 'account_type', render: (t: AccountType) => <Tag color={ACCOUNT_TYPE_COLORS[t]}>{ACCOUNT_TYPE_LABELS[t]}</Tag> },
        { title: 'Payment method', dataIndex: 'payment_method_name', render: (v: string | null) => v ?? '—' },
        { title: 'Account no.', dataIndex: 'account_number', render: (v: string) => v || <Typography.Text type="secondary">—</Typography.Text> },
        { title: <span style={{ display: 'block', textAlign: 'right' }}>Balance</span>, dataIndex: 'balance', render: (v: string) => <MoneyText value={v} strong /> },
      ]}
      renderForm={({ record }) => (
        <>
          <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 100 }]}>
            <Input placeholder="e.g. City Bank (current)" />
          </Form.Item>
          <Form.Item name="account_type" label="Type" rules={[{ required: true }]}>
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="payment_method_id" label="Payment method">
            <Select allowClear options={methods} loading={lookups.isPending} placeholder="Optional" />
          </Form.Item>
          <Form.Item name="account_number" label="Account / wallet number" rules={[{ max: 50 }]}>
            <Input />
          </Form.Item>
          {record ? (
            <Typography.Paragraph type="secondary">
              Opening balance {formatDecimal(record.opening_balance, 2)} was posted when the account was created. Balances change only
              through vouchers.
            </Typography.Paragraph>
          ) : (
            <Form.Item name="opening_balance" label="Opening balance" extra="Posted to the account ledger as the opening entry.">
              <InputNumber<string> stringMode min="0" precision={2} style={{ width: '100%' }} />
            </Form.Item>
          )}
        </>
      )}
    />
  );
}
