import { ArrowLeftOutlined, DollarOutlined, PrinterOutlined, RollbackOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Col, Descriptions, Divider, Flex, Row, Skeleton, Table, Typography } from 'antd';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { SALES, salesApi } from '../../api/sales';
import type { InvoiceDetail, InvoiceItem } from '../../api/sales';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import QtyText from '../../components/QtyText';
import StatusTag from '../../components/StatusTag';
import { usePermission } from '../../hooks/usePermission';
import { compare, formatDecimal } from '../../utils/decimal';
import SalesReturnModal from './SalesReturnModal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

function Totals({ inv }: { inv: InvoiceDetail }) {
  const rows: [string, string, boolean?][] = [
    ['Subtotal', inv.subtotal],
    ...(compare(inv.discount, 0) > 0 ? ([['Discount', `-${inv.discount}`]] as [string, string][]) : []),
    ['Invoice total', inv.total, true],
    ...(compare(inv.returned_amount, 0) > 0 ? ([['Returned', `-${inv.returned_amount}`]] as [string, string][]) : []),
    ...(compare(inv.refunded_amount, 0) > 0 ? ([['Refunded', inv.refunded_amount]] as [string, string][]) : []),
    ['Paid', `-${inv.paid_amount}`],
    ['Outstanding', inv.outstanding, true],
  ];
  return (
    <Flex vertical align="flex-end" gap={4} style={{ marginTop: 12 }}>
      {rows.map(([label, value, strong]) => (
        <Flex key={label} gap={24} style={{ minWidth: 280 }} justify="space-between">
          <Typography.Text strong={strong}>{label}</Typography.Text>
          <MoneyText value={value} strong={strong} />
        </Flex>
      ))}
    </Flex>
  );
}

export default function InvoicePage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const canCollect = usePermission('collection.create');
  const canReturn = usePermission('sales_return.create');
  const [returning, setReturning] = useState<InvoiceDetail | null>(null);

  const invoice = useQuery({
    queryKey: [SALES.invoices, 'detail', id],
    queryFn: () => salesApi.invoice(id),
    enabled: Number.isInteger(id),
  });

  if (invoice.isError) return <ErrorState error={invoice.error} onRetry={() => invoice.refetch()} />;
  if (!invoice.data) return <Skeleton active />;
  const inv = invoice.data;
  const company = inv.company;
  const returnable = inv.items.some((i) => compare(i.qty_returnable, 0) > 0);
  const collectUrl = `/money/collections?customer_id=${inv.customer_id}&invoice_id=${inv.id}&amount=${inv.outstanding}`;

  return (
    <>
      <Flex justify="space-between" gap={8} wrap className="no-print" style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(SALES.invoices)}>Invoices</Button>
        <Flex gap={8} wrap>
          {canReturn && returnable && (
            <Button icon={<RollbackOutlined />} onClick={() => setReturning(inv)}>
              Sales return
            </Button>
          )}
          {canCollect && compare(inv.outstanding, 0) > 0 && (
            <Button icon={<DollarOutlined />} onClick={() => navigate(collectUrl)}>
              Collect payment
            </Button>
          )}
          <Button type="primary" icon={<PrinterOutlined />} onClick={() => window.print()}>
            Print
          </Button>
        </Flex>
      </Flex>

      <Card>
        <Row gutter={[24, 16]} justify="space-between">
          <Col span={14}>
            {company.logo_url && <img src={company.logo_url} alt="" style={{ maxHeight: 56, marginBottom: 8 }} />}
            {company.company_name && <Typography.Title level={4} style={{ margin: 0 }}>{company.company_name}</Typography.Title>}
            {company.address && <div>{company.address}</div>}
            <Typography.Text type="secondary">{[company.phone, company.email].filter(Boolean).join(' · ')}</Typography.Text>
          </Col>
          <Col span={10} style={{ textAlign: 'right' }}>
            <Typography.Title level={3} style={{ margin: 0 }}>INVOICE</Typography.Title>
            <Flex justify="flex-end" gap={8} align="center">
              <strong>{inv.inv_number}</strong>
              <StatusTag status={inv.status} />
            </Flex>
            <div>Date: <DateText value={inv.invoice_date} /></div>
            <Typography.Text type="secondary">
              Order <Link to={`${SALES.orders}/${inv.sales_order_id}`}>{inv.so_number}</Link> · Delivery {inv.dlv_number}
            </Typography.Text>
          </Col>
        </Row>
        <Divider style={{ margin: '16px 0' }} />
        <Descriptions
          size="small"
          column={{ xs: 1, md: 2 }}
          items={[
            { label: 'Bill to', children: <strong>{inv.customer_code} {inv.customer_name}</strong> },
            { label: 'Delivered from', children: inv.warehouse_name },
            ...(inv.customer_mobile ? [{ label: 'Mobile', children: inv.customer_mobile }] : []),
            ...(inv.customer_address ? [{ label: 'Address', children: inv.customer_address }] : []),
          ]}
        />
        <Table<InvoiceItem>
          rowKey="id"
          size="small"
          pagination={false}
          style={{ marginTop: 16 }}
          dataSource={inv.items}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '#', key: 'n', width: 40, render: (_, __, i) => i + 1 },
            { title: 'Product', key: 'p', render: (_, i) => <>{i.product_code} {i.product_name}</> },
            { title: right('Qty'), dataIndex: 'qty', render: (v: string, i) => <QtyText value={v} unit={i.unit_code} /> },
            { title: right('Unit price'), dataIndex: 'unit_price', render: (v: string) => <MoneyText value={v} /> },
            { title: right('Amount'), dataIndex: 'line_total', render: (v: string) => <MoneyText value={v} /> },
            { title: right('Returned'), dataIndex: 'qty_returned', render: (v: string) => (compare(v, 0) > 0 ? <QtyText value={v} /> : null) },
          ]}
        />
        <Totals inv={inv} />
        {company.invoice_footer_note && (
          <Typography.Paragraph type="secondary" style={{ marginTop: 24, textAlign: 'center' }}>
            {company.invoice_footer_note}
          </Typography.Paragraph>
        )}
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }} className="no-print">
        <Col xs={24} lg={12}>
          <Card size="small" title="Collections">
            {inv.collections.length === 0 ? (
              <Typography.Text type="secondary">No payments linked to this invoice yet.</Typography.Text>
            ) : (
              inv.collections.map((c) => (
                <Flex key={c.id} justify="space-between" gap={8} style={{ marginBottom: 4 }}>
                  <span>
                    <strong>{c.number}</strong> <DateText value={c.collection_date} /> · {c.account_name} <StatusTag status={c.status} />
                  </span>
                  <MoneyText value={c.amount} />
                </Flex>
              ))
            )}
            <Divider style={{ margin: '8px 0' }} />
            <Typography.Text type="secondary">Customer's total due (all invoices): {formatDecimal(inv.customer_due, 2)}</Typography.Text>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="Sales returns">
            {inv.returns.length === 0 ? (
              <Typography.Text type="secondary">No returns.</Typography.Text>
            ) : (
              inv.returns.map((r) => (
                <Alert
                  key={r.id}
                  type="warning"
                  style={{ marginBottom: 8 }}
                  title={
                    <>
                      <strong>{r.srn_number}</strong> on <DateText value={r.return_date} />:{' '}
                      {r.items.map((i) => `${formatDecimal(i.qty, 3, true)} ${i.unit_code} ${i.product_code}`).join(', ')}, credited{' '}
                      <strong>{formatDecimal(r.total, 2)}</strong>
                      {compare(r.refund_amount, 0) > 0 && <>, refunded {formatDecimal(r.refund_amount, 2)} from {r.refund_account_name}</>}
                    </>
                  }
                />
              ))
            )}
          </Card>
        </Col>
      </Row>

      <SalesReturnModal invoice={returning} onClose={() => setReturning(null)} />
    </>
  );
}
