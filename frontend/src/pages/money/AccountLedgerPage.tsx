import { DatePicker, Empty, Flex, Select, Table, Tag, Typography } from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import { useSearchParams } from 'react-router';

import { useLookups } from '../../api/master';
import { MONEY } from '../../api/money';
import type { AccountLedgerPage as LedgerPage, AccountLedgerRow } from '../../api/money';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import { useList } from '../../hooks/useApi';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  OPENING: { label: 'Opening', color: 'blue' },
  COLLECTION: { label: 'Collection', color: 'green' },
  SUPPLIER_PAYMENT: { label: 'Supplier payment', color: 'volcano' },
  EXPENSE: { label: 'Expense', color: 'red' },
  INCOME: { label: 'Income', color: 'cyan' },
  TRANSFER_OUT: { label: 'Transfer out', color: 'orange' },
  TRANSFER_IN: { label: 'Transfer in', color: 'geekblue' },
  PAYROLL: { label: 'Payroll', color: 'purple' },
  REFUND: { label: 'Refund', color: 'magenta' },
};

type Row = AccountLedgerRow & { opening?: boolean };

export default function AccountLedgerPage() {
  const lookups = useLookups();
  const [params, setParams] = useSearchParams();
  const accountId = Number(params.get('account_id')) || undefined;
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

  const ledger = useList<AccountLedgerRow>(
    `${MONEY.accounts}/${accountId}/ledger`,
    { from, to, page, page_size: pageSize },
    !!accountId,
  );
  const data = ledger.data as LedgerPage | undefined;

  const rows: Row[] =
    data && page === 1
      ? [
          {
            id: 0,
            opening: true,
            txn_date: from ?? '',
            txn_type: '',
            direction: 'in',
            amount: '',
            money_in: '',
            money_out: '',
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
    { title: 'Date', dataIndex: 'txn_date', width: 120, render: (v: string, r) => (r.opening && !v ? '—' : <DateText value={v} />) },
    {
      title: 'Type',
      dataIndex: 'txn_type',
      render: (t: string, r) =>
        r.opening ? (
          <Typography.Text italic>Opening balance</Typography.Text>
        ) : (
          <>
            <Tag color={TYPE_LABELS[t]?.color}>{TYPE_LABELS[t]?.label ?? t}</Tag>
            {r.reversal_of_id && <Tag>reversal</Tag>}
          </>
        ),
    },
    { title: 'Reference', dataIndex: 'note', render: (v: string, r) => (r.opening ? null : v) },
    { title: right('In'), dataIndex: 'money_in', render: (v: string) => (v && Number(v) ? <MoneyText value={v} /> : null) },
    { title: right('Out'), dataIndex: 'money_out', render: (v: string) => (v && Number(v) ? <MoneyText value={v} /> : null) },
    { title: right('Balance'), dataIndex: 'running_balance', render: (v: string) => <MoneyText value={v} strong /> },
    { title: 'By', dataIndex: 'created_by_name', render: (v: string | null) => v ?? '' },
  ];

  return (
    <>
      <PageHeader title="Account Ledger" subtitle={data?.account_name ?? 'Every money movement of one account.'} />
      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        <Select
          placeholder="Choose an account"
          style={{ width: 260 }}
          value={accountId}
          options={(lookups.data?.money_accounts ?? []).map((a) => ({ label: a.name, value: a.id }))}
          onChange={(v: number) => set({ account_id: v })}
        />
        <DatePicker.RangePicker
          allowEmpty={[true, true]}
          value={[from ? dayjs(from) : null, to ? dayjs(to) : null]}
          onChange={(v) => set({ from: v?.[0]?.format('YYYY-MM-DD'), to: v?.[1]?.format('YYYY-MM-DD') })}
        />
      </Flex>
      {!accountId ? (
        <Empty description="Choose an account to see its movements" style={{ marginTop: 48 }} />
      ) : ledger.isError ? (
        <ErrorState error={ledger.error} onRetry={() => ledger.refetch()} />
      ) : (
        <Table<Row>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={rows}
          loading={ledger.isFetching}
          scroll={{ x: 'max-content' }}
          onRow={(r) => ({ style: r.opening ? { background: 'var(--ant-color-fill-quaternary, #fafafa)' } : undefined })}
          locale={{ emptyText: 'No movements in this period' }}
          summary={() =>
            data ? (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={5} align="right">
                  <strong>Closing balance{to ? ` on ${dayjs(to).format('DD MMM YYYY')}` : ''}</strong>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={1}>
                  <MoneyText value={data.closing_balance} strong />
                </Table.Summary.Cell>
                <Table.Summary.Cell index={2} />
              </Table.Summary.Row>
            ) : null
          }
          pagination={{
            current: page,
            pageSize,
            total: data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (t) => `${t} movements`,
            onChange: (p, ps) => set({ page: ps !== pageSize ? 1 : p, page_size: ps }),
          }}
        />
      )}
    </>
  );
}
