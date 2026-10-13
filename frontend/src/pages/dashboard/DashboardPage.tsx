import { ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Col, Empty, Flex, Row, Skeleton, Table, Typography, theme } from 'antd';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import dayjs from 'dayjs';

import { useDashboard } from '../../api/dashboard';
import type { DashboardSummary, LowStockRow, PartyDue } from '../../api/dashboard';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import QtyText from '../../components/QtyText';
import { useAuth } from '../../hooks/useAuth';
import { usePermission } from '../../hooks/usePermission';
import { formatDecimal } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

interface Metric {
  key: keyof DashboardSummary;
  label: string;
  hint?: string;
  link?: string;
  render?: (d: DashboardSummary) => ReactNode;
}

const GROUPS: { title: string; metrics: Metric[] }[] = [
  {
    title: 'Today',
    metrics: [
      { key: 'today_sales', label: "Today's sales", hint: 'Invoices - sales returns', link: '/sales/invoices' },
      { key: 'today_collection', label: "Today's collection", link: '/money/collections' },
      { key: 'today_expenses', label: "Today's expenses", hint: 'Incl. payroll', link: '/money/expenses' },
      { key: 'today_purchase', label: "Today's purchase", hint: 'Receipts - purchase returns', link: '/purchase/receipts' },
    ],
  },
  {
    title: 'Money',
    metrics: [
      { key: 'cash_balance', label: 'Cash', link: '/money/accounts' },
      { key: 'bank_balance', label: 'Bank', link: '/money/accounts' },
      { key: 'mfs_balance', label: 'Mobile (MFS)', link: '/money/accounts' },
    ],
  },
  {
    title: 'Dues',
    metrics: [
      { key: 'customer_due', label: 'Customer due', hint: 'Receivable', link: '/customers' },
      { key: 'supplier_due', label: 'Supplier due', hint: 'Payable', link: '/suppliers' },
    ],
  },
  {
    title: 'Stock & Orders',
    metrics: [
      { key: 'inventory_value', label: 'Inventory value', hint: 'At average cost', link: '/inventory/stock' },
      {
        key: 'pending_orders_count',
        label: 'Pending orders',
        link: '/sales/orders',
        render: (d) => (
          <>
            <Typography.Text style={{ fontSize: 24, fontWeight: 600 }}>{d.pending_orders_count}</Typography.Text>
            <Typography.Text type="secondary"> worth {formatDecimal(d.pending_orders_value, 2)}</Typography.Text>
          </>
        ),
      },
    ],
  },
  {
    title: 'Profit',
    metrics: [{ key: 'estimated_profit_mtd', label: 'Estimated profit (month to date)', hint: 'Net sales - COGS + other income - expenses' }],
  },
];

function MetricCard({ metric, data }: { metric: Metric; data: DashboardSummary }) {
  const value = data[metric.key] as string;
  const negative = typeof value === 'string' && value.startsWith('-');
  const body = metric.render ? (
    metric.render(data)
  ) : (
    <MoneyText value={value} strong style={{ fontSize: 24, textAlign: 'left', color: negative ? 'var(--ant-color-error, #ff4d4f)' : undefined }} />
  );
  return (
    <Card size="small" style={{ height: '100%' }}>
      <Flex justify="space-between" align="baseline">
        <Typography.Text type="secondary">{metric.label}</Typography.Text>
        {metric.link && <Link to={metric.link} style={{ fontSize: 12 }}>View</Link>}
      </Flex>
      <div style={{ marginTop: 4 }}>{body}</div>
      {metric.hint && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{metric.hint}</Typography.Text>}
    </Card>
  );
}

function DueTable({ title, rows, kind }: { title: string; rows: PartyDue[]; kind: 'customers' | 'suppliers' }) {
  const canStatement = usePermission('party_statement.view');
  return (
    <Card size="small" title={title} style={{ height: '100%' }}>
      <Table<PartyDue>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={rows}
        locale={{ emptyText: 'Nothing due' }}
        columns={[
          { title: 'Code', dataIndex: 'code' },
          {
            title: 'Name',
            key: 'name',
            render: (_, r) => (canStatement ? <Link to={`/${kind}/${r.id}/statement`}>{r.name}</Link> : r.name),
          },
          { title: right('Due'), dataIndex: 'due', render: (v: string) => <MoneyText value={v} strong /> },
        ]}
      />
    </Card>
  );
}

function SalesChart({ data }: { data: DashboardSummary }) {
  const { token } = theme.useToken();
  const points = (data.sales_vs_collection ?? []).map((p) => ({
    day: dayjs(p.date).format('DD MMM'),
    ...(p.sales != null ? { Sales: Number(p.sales) } : {}),
    ...(p.collection != null ? { Collection: Number(p.collection) } : {}),
  }));
  const hasSales = data.sales_vs_collection?.some((p) => p.sales != null);
  const hasCollection = data.sales_vs_collection?.some((p) => p.collection != null);
  return (
    <Card size="small" title="Last 7 days: sales vs collection" style={{ height: '100%' }}>
      <div style={{ width: '100%', height: 260 }} aria-label="Sales vs collection chart">
        <ResponsiveContainer>
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={token.colorBorderSecondary} />
            <XAxis dataKey="day" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} width={70} tickFormatter={(v: number) => formatDecimal(String(v), 0)} />
            <Tooltip formatter={(v) => formatDecimal(String(v), 2)} />
            <Legend />
            {hasSales && <Line type="linear" dataKey="Sales" stroke={token.colorPrimary} strokeWidth={2} dot={{ r: 3 }} />}
            {hasCollection && <Line type="linear" dataKey="Collection" stroke={token.colorSuccess} strokeWidth={2} dot={{ r: 3 }} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const dashboard = useDashboard();

  if (dashboard.isError) return <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />;
  const d = dashboard.data;
  const groups = d
    ? GROUPS.map((g) => ({ ...g, metrics: g.metrics.filter((m) => d[m.key] !== undefined) })).filter((g) => g.metrics.length)
    : [];

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={
          d ? (
            <>
              Welcome, {user?.full_name}. Figures for <DateText value={d.as_of} /> (month from <DateText value={d.month_start} />), updated{' '}
              <DateText value={d.generated_at} withTime />. Refreshes every minute.
            </>
          ) : (
            `Welcome, ${user?.full_name ?? ''}`
          )
        }
        actions={
          <Button icon={<ReloadOutlined />} loading={dashboard.isFetching} onClick={() => dashboard.refetch()}>
            Refresh
          </Button>
        }
      />
      {!d ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : groups.length === 0 && !d.low_stock && !d.sales_vs_collection ? (
        <Empty description="Nothing on the dashboard for your role yet" />
      ) : (
        <>
          {groups.map((g) => (
            <div key={g.title} style={{ marginBottom: 16 }}>
              <Typography.Title level={5} style={{ marginBottom: 8 }}>
                {g.title}
              </Typography.Title>
              <Row gutter={[12, 12]}>
                {g.metrics.map((m) => (
                  <Col key={m.key} xs={24} sm={12} lg={6}>
                    <MetricCard metric={m} data={d} />
                  </Col>
                ))}
              </Row>
            </div>
          ))}
          <Row gutter={[12, 12]} style={{ marginTop: 8 }}>
            {d.sales_vs_collection && (
              <Col xs={24} xl={12}>
                <SalesChart data={d} />
              </Col>
            )}
            {d.low_stock && (
              <Col xs={24} xl={12}>
                <Card size="small" title="Low stock" extra={<Link to="/inventory/stock">Current stock</Link>} style={{ height: '100%' }}>
                  <Table<LowStockRow>
                    rowKey={(r) => `${r.product_id}-${r.warehouse_name}`}
                    size="small"
                    pagination={false}
                    dataSource={d.low_stock}
                    locale={{ emptyText: 'Nothing below its reorder level' }}
                    columns={[
                      { title: 'Product', key: 'p', render: (_, r) => <>{r.product_code} {r.product_name}</> },
                      { title: 'Warehouse', dataIndex: 'warehouse_name' },
                      { title: right('On hand'), dataIndex: 'qty_on_hand', render: (v: string) => <QtyText value={v} /> },
                      { title: right('Reorder at'), dataIndex: 'reorder_level', render: (v: string) => <QtyText value={v} /> },
                    ]}
                  />
                </Card>
              </Col>
            )}
            {d.top_customers && (
              <Col xs={24} xl={12}>
                <DueTable title="Top customers by due" rows={d.top_customers} kind="customers" />
              </Col>
            )}
            {d.top_suppliers && (
              <Col xs={24} xl={12}>
                <DueTable title="Top suppliers by due" rows={d.top_suppliers} kind="suppliers" />
              </Col>
            )}
          </Row>
        </>
      )}
    </>
  );
}
