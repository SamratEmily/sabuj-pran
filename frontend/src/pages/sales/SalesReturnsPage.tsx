import { RollbackOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { Button, Card, Flex, Select, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { SALES, salesApi } from '../../api/sales';
import type { Invoice, InvoiceDetail, SalesReturnDoc } from '../../api/sales';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { notifyError } from '../../utils/notify';
import { formatDecimal } from '../../utils/decimal';
import { useCustomerOptions } from './SalesDocForm';
import SalesReturnModal from './SalesReturnModal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

/** Pick an invoice (search by number or customer), then open the return form for it. */
function NewReturn({ onPicked }: { onPicked: (invoice: InvoiceDetail) => void }) {
  const [search, setSearch] = useState('');
  const [invoiceId, setInvoiceId] = useState<number | undefined>();
  const invoices = useList<Invoice>(SALES.invoices, { search, page_size: 20 });
  const load = useMutation({
    mutationFn: (id: number) => salesApi.invoice(id),
    meta: { silent: true },
    onSuccess: onPicked,
    onError: (error) => notifyError(error, 'Could not load the invoice'),
  });
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Flex gap={8} wrap align="center">
        <Typography.Text>Return goods from invoice:</Typography.Text>
        <Select
          showSearch={{ filterOption: false, onSearch: setSearch }}
          value={invoiceId}
          onChange={setInvoiceId}
          placeholder="Search invoice number or customer"
          style={{ width: 360, maxWidth: '100%' }}
          loading={invoices.isFetching}
          options={(invoices.data?.items ?? []).map((i) => ({
            value: i.id,
            label: `${i.inv_number} · ${i.customer_name} · ${formatDecimal(i.total, 2)}`,
          }))}
        />
        <Button icon={<RollbackOutlined />} disabled={!invoiceId} loading={load.isPending} onClick={() => invoiceId && load.mutate(invoiceId)}>
          Return goods
        </Button>
      </Flex>
    </Card>
  );
}

export default function SalesReturnsPage() {
  const customers = useCustomerOptions();
  const canCreate = usePermission('sales_return.create');
  const canViewInvoices = usePermission('invoice.view');
  const [returning, setReturning] = useState<InvoiceDetail | null>(null);
  return (
    <>
      <CrudPage<SalesReturnDoc>
        title="Sales Returns"
        endpoint={SALES.returns}
        permission="sales_return"
        itemName="sales return"
        searchPlaceholder="Return number or customer"
        creatable={false}
        editable={false}
        deactivatable={false}
        dateRangeFilter
        filters={[{ name: 'customer_id', label: 'Customer', options: customers.options, width: 220 }]}
        headerExtra={canCreate && canViewInvoices ? <NewReturn onPicked={setReturning} /> : null}
        columns={[
          { title: 'Return', dataIndex: 'srn_number', render: (v: string) => <strong>{v}</strong> },
          { title: 'Date', dataIndex: 'return_date', render: (v: string) => <DateText value={v} /> },
          { title: 'Customer', key: 'c', render: (_, r) => <>{r.customer_code} {r.customer_name}</> },
          { title: 'Invoice', key: 'inv', render: (_, r) => (canViewInvoices ? <Link to={`${SALES.invoices}/${r.invoice_id}`}>{r.inv_number}</Link> : r.inv_number) },
          {
            title: 'Items',
            key: 'items',
            render: (_, r) => r.items.map((i) => `${formatDecimal(i.qty, 3, true)} ${i.unit_code} ${i.product_code}`).join(', '),
          },
          { title: right('Credited'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
          {
            title: right('Refunded'),
            key: 'refund',
            render: (_, r) => <MoneyText value={r.refund_amount} />,
          },
          { title: 'Refund from', dataIndex: 'refund_account_name', render: (v: string | null) => v ?? '—' },
          { title: 'By', dataIndex: 'created_by_name' },
        ]}
        renderForm={() => null}
      />
      <SalesReturnModal invoice={returning} onClose={() => setReturning(null)} />
    </>
  );
}
