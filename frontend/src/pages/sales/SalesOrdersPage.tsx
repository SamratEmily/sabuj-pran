import dayjs from 'dayjs';
import { Link, useNavigate } from 'react-router';

import { useLookups } from '../../api/master';
import { SALES } from '../../api/sales';
import type { SalesOrder } from '../../api/sales';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import { newLine } from '../../components/DocLineItems';
import MoneyText from '../../components/MoneyText';
import StatusTag from '../../components/StatusTag';
import SalesDocForm, { linesPayload, SALES_ERROR_FIELDS, toLines, useCustomerOptions } from './SalesDocForm';
import type { SalesDocValues } from './SalesDocForm';

export const SO_STATUS_OPTIONS = [
  { label: 'Draft', value: 'draft' },
  { label: 'Confirmed', value: 'confirmed' },
  { label: 'Partially delivered', value: 'partially_delivered' },
  { label: 'Delivered', value: 'delivered' },
  { label: 'Cancelled', value: 'cancelled' },
];

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

export default function SalesOrdersPage() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const customers = useCustomerOptions();
  const defaultWarehouse = lookups.data?.warehouses.find((w) => w.is_default)?.id;

  return (
    <CrudPage<SalesOrder, SalesDocValues>
      title="Sales Orders"
      endpoint={SALES.orders}
      permission="sales_order"
      itemName="sales order"
      searchPlaceholder="SO number or customer"
      deactivatable={false}
      dateRangeFilter
      canEditRow={(so) => so.status === 'draft'}
      formWidth={1080}
      filters={[
        { name: 'customer_id', label: 'Customer', options: customers.options, width: 220 },
        { name: 'status', label: 'Status', options: SO_STATUS_OPTIONS },
      ]}
      initialValues={{ warehouse_id: defaultWarehouse, date: dayjs(), discount: '0', notes: '', items: [newLine()] }}
      errorFields={SALES_ERROR_FIELDS}
      toFormValues={(so) => ({
        customer_id: so.customer_id,
        warehouse_id: so.warehouse_id,
        date: dayjs(so.order_date),
        second_date: so.delivery_date ? dayjs(so.delivery_date) : null,
        discount: so.discount,
        notes: so.notes,
        items: toLines(so.items.map((i) => ({ ...i, qty: i.qty_ordered }))),
      })}
      toPayload={(v) => ({
        ...linesPayload(v),
        warehouse_id: v.warehouse_id,
        order_date: v.date.format('YYYY-MM-DD'),
        delivery_date: v.second_date ? v.second_date.format('YYYY-MM-DD') : null,
      })}
      onSaved={(so) => navigate(`${SALES.orders}/${so.id}`)}
      columns={[
        {
          title: 'Order',
          key: 'n',
          render: (_, so) => (
            <Link to={`${SALES.orders}/${so.id}`}>
              <strong>{so.so_number}</strong>
            </Link>
          ),
        },
        { title: 'Date', dataIndex: 'order_date', render: (v: string) => <DateText value={v} /> },
        { title: 'Customer', key: 'c', render: (_, so) => <>{so.customer_code} {so.customer_name}</> },
        { title: 'Warehouse', dataIndex: 'warehouse_name' },
        { title: 'Delivery by', dataIndex: 'delivery_date', render: (v: string | null) => <DateText value={v} /> },
        { title: right('Total'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
        { title: 'Status', dataIndex: 'status', render: (s: string) => <StatusTag status={s} /> },
      ]}
      renderForm={() => <SalesDocForm dateLabel="Order date" secondDateLabel="Delivery by" withWarehouse />}
    />
  );
}
