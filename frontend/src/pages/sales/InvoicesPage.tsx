import { Link } from 'react-router';

import { SALES } from '../../api/sales';
import type { Invoice } from '../../api/sales';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import StatusTag from '../../components/StatusTag';
import { useCustomerOptions } from './SalesDocForm';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

export default function InvoicesPage() {
  const customers = useCustomerOptions();
  return (
    <CrudPage<Invoice>
      title="Invoices"
      endpoint={SALES.invoices}
      permission="invoice"
      itemName="invoice"
      searchPlaceholder="Invoice number or customer"
      creatable={false}
      editable={false}
      deactivatable={false}
      dateRangeFilter
      filters={[
        { name: 'customer_id', label: 'Customer', options: customers.options, width: 220 },
        {
          name: 'status',
          label: 'Status',
          options: [
            { label: 'Unpaid', value: 'unpaid' },
            { label: 'Partial', value: 'partial' },
            { label: 'Paid', value: 'paid' },
          ],
        },
      ]}
      columns={[
        { title: 'Invoice', key: 'n', render: (_, inv) => <Link to={`${SALES.invoices}/${inv.id}`}><strong>{inv.inv_number}</strong></Link> },
        { title: 'Date', dataIndex: 'invoice_date', render: (v: string) => <DateText value={v} /> },
        { title: 'Customer', key: 'c', render: (_, inv) => <>{inv.customer_code} {inv.customer_name}</> },
        { title: 'Order', key: 'so', render: (_, inv) => <Link to={`${SALES.orders}/${inv.sales_order_id}`}>{inv.so_number}</Link> },
        { title: right('Total'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
        { title: right('Paid'), dataIndex: 'paid_amount', render: (v: string) => <MoneyText value={v} /> },
        { title: right('Outstanding'), dataIndex: 'outstanding', render: (v: string) => <MoneyText value={v} /> },
        { title: 'Status', dataIndex: 'status', render: (s: string) => <StatusTag status={s} /> },
      ]}
      renderForm={() => null}
    />
  );
}
