import { ArrowLeftOutlined, PrinterOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, DatePicker, Descriptions, Flex, Skeleton, Table, Typography } from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import { PARTY_ENDPOINT, partiesApi } from '../../api/parties';
import type { PartyKind, StatementEntry } from '../../api/parties';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import { statusLabel } from '../../components/StatusTag';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

type Row = StatementEntry & { opening?: boolean };

export default function StatementPage({ kind }: { kind: PartyKind }) {
  const { id } = useParams();
  const partyId = Number(id);
  const navigate = useNavigate();
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().startOf('month'), dayjs()]);
  const from = range[0].format('YYYY-MM-DD');
  const to = range[1].format('YYYY-MM-DD');

  const statement = useQuery({
    queryKey: [PARTY_ENDPOINT[kind], partyId, 'statement', from, to],
    queryFn: () => partiesApi.statement(kind, partyId, from, to),
    enabled: Number.isInteger(partyId),
  });

  const isCustomer = kind === 'customers';
  const title = isCustomer ? 'Customer Statement' : 'Supplier Statement';
  const balanceLabel = isCustomer ? 'Balance (due)' : 'Balance (payable)';
  const data = statement.data;

  const rows: Row[] = data
    ? [
        {
          id: 0,
          opening: true,
          entry_date: data.date_from ?? '',
          ref_type: 'OPENING_BALANCE',
          ref_id: null,
          note: 'Balance brought forward',
          debit: '',
          credit: '',
          balance: data.opening_balance,
        },
        ...data.entries,
      ]
    : [];

  const columns: TableProps<Row>['columns'] = [
    { title: 'Date', dataIndex: 'entry_date', width: 120, render: (v: string) => <DateText value={v} /> },
    {
      title: 'Reference',
      key: 'ref',
      render: (_, r) => (
        <>
          {statusLabel(r.ref_type.toLowerCase())}
          {r.ref_id !== null && !r.ref_type.startsWith('OPENING') && <Typography.Text type="secondary"> #{r.ref_id}</Typography.Text>}
        </>
      ),
    },
    { title: 'Note', dataIndex: 'note', render: (v: string) => v || '—' },
    { title: right('Debit'), dataIndex: 'debit', width: 130, render: (v: string) => (v ? <MoneyText value={v} /> : null) },
    { title: right('Credit'), dataIndex: 'credit', width: 130, render: (v: string) => (v ? <MoneyText value={v} /> : null) },
    { title: right(balanceLabel), dataIndex: 'balance', width: 150, render: (v: string) => <MoneyText value={v} strong signed /> },
  ];

  return (
    <>
      <div className="no-print">
        <PageHeader
          title={title}
          actions={
            <>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(PARTY_ENDPOINT[kind])}>
                Back
              </Button>
              <Button type="primary" icon={<PrinterOutlined />} onClick={() => window.print()} disabled={!data}>
                Print
              </Button>
            </>
          }
        />
        <Flex gap={8} style={{ marginBottom: 16 }}>
          <DatePicker.RangePicker
            allowClear={false}
            value={range}
            onChange={(v) => v?.[0] && v[1] && setRange([v[0], v[1]])}
            presets={[
              { label: 'This month', value: [dayjs().startOf('month'), dayjs()] },
              { label: 'Last month', value: [dayjs().subtract(1, 'month').startOf('month'), dayjs().subtract(1, 'month').endOf('month')] },
              { label: 'This year', value: [dayjs().startOf('year'), dayjs()] },
              { label: 'Last 12 months', value: [dayjs().subtract(12, 'month'), dayjs()] },
            ]}
          />
        </Flex>
      </div>

      {statement.isError ? (
        <ErrorState error={statement.error} onRetry={() => statement.refetch()} />
      ) : !data ? (
        <Skeleton active />
      ) : (
        <Card variant="borderless" styles={{ body: { padding: 0 } }}>
          <Typography.Title level={4} className="print-only" style={{ marginTop: 0 }}>
            {title}
          </Typography.Title>
          <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ marginBottom: 16 }}>
            <Descriptions.Item label={isCustomer ? 'Customer' : 'Supplier'}>
              <strong>{data.party.name}</strong>&nbsp;({data.party.code})
            </Descriptions.Item>
            <Descriptions.Item label="Mobile">{data.party.mobile || '—'}</Descriptions.Item>
            <Descriptions.Item label="Period">
              <DateText value={data.date_from} /> – <DateText value={data.date_to} />
            </Descriptions.Item>
            <Descriptions.Item label="Address" span="filled">
              {data.party.address || '—'}
            </Descriptions.Item>
          </Descriptions>
          <Table<Row>
            rowKey="id"
            size="small"
            pagination={false}
            columns={columns}
            dataSource={rows}
            loading={statement.isFetching}
            scroll={{ x: 'max-content' }}
            onRow={(r) => ({ style: r.opening ? { fontStyle: 'italic' } : undefined })}
            locale={{ emptyText: 'No entries in this period' }}
            summary={() => (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={3} align="right">
                  <strong>Totals / closing balance</strong>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={3}>
                  <MoneyText value={data.total_debit} strong />
                </Table.Summary.Cell>
                <Table.Summary.Cell index={4}>
                  <MoneyText value={data.total_credit} strong />
                </Table.Summary.Cell>
                <Table.Summary.Cell index={5}>
                  <MoneyText value={data.closing_balance} strong signed />
                </Table.Summary.Cell>
              </Table.Summary.Row>
            )}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
            {isCustomer
              ? 'Debit = invoices, refunds and opening due. Credit = collections and returns. A positive balance is owed by the customer.'
              : 'Credit = goods received and opening due. Debit = payments and returns. A positive balance is owed to the supplier.'}
            {' '}Printed <DateText value={new Date().toISOString()} withTime />.
          </Typography.Paragraph>
        </Card>
      )}
    </>
  );
}
