import { Col, DatePicker, Descriptions, Form, Input, InputNumber, Row, Select } from 'antd';
import type { Dayjs } from 'dayjs';

import { useLookups } from '../../api/master';
import type { PartyRecord } from '../../api/parties';
import type { LinesPayload } from '../../api/sales';
import DocLineItems, { linesTotal, newLine, validateLines } from '../../components/DocLineItems';
import type { DocLine } from '../../components/DocLineItems';
import PartyDue from '../../components/PartyDue';
import { useList } from '../../hooks/useApi';
import { compare, formatDecimal, subtract } from '../../utils/decimal';

/** Form values shared by quotations and sales orders. */
export interface SalesDocValues {
  customer_id: number;
  warehouse_id?: number;
  date: Dayjs;
  second_date?: Dayjs | null;
  discount?: string | null;
  notes?: string;
  items: DocLine[];
}

export const SALES_ERROR_FIELDS: Record<string, string> = {
  INVALID_CUSTOMER: 'customer_id',
  INACTIVE_CUSTOMER: 'customer_id',
  INVALID_WAREHOUSE: 'warehouse_id',
  INACTIVE_WAREHOUSE: 'warehouse_id',
  INVALID_DISCOUNT: 'discount',
  DUPLICATE_LINE: 'items',
  INVALID_PRODUCT: 'items',
  INACTIVE_PRODUCT: 'items',
};

export function linesPayload(v: SalesDocValues): LinesPayload {
  return {
    customer_id: v.customer_id,
    discount: v.discount || '0',
    notes: v.notes ?? '',
    items: v.items.map((l) => ({ product_id: l.product_id!, qty: l.qty!, unit_price: l.price! })),
  };
}

interface SavedLine {
  product_id: number;
  product_code: string;
  product_name: string;
  unit_price: string;
  qty: string;
}

export function toLines(items: SavedLine[]): DocLine[] {
  return items.map((i) => newLine({ product_id: i.product_id, product_name: `${i.product_code} ${i.product_name}`, qty: i.qty, price: i.unit_price }));
}

export function useCustomerOptions() {
  const customers = useList<PartyRecord>('/customers', { page_size: 100, is_active: true });
  return {
    options: (customers.data?.items ?? []).map((c) => ({ label: `${c.code} ${c.name}`, value: c.id })),
    loading: customers.isPending,
  };
}

interface Props {
  dateLabel: string;
  secondDateLabel: string;
  /** Sales orders choose the warehouse and see available stock per line. */
  withWarehouse?: boolean;
}

export default function SalesDocForm({ dateLabel, secondDateLabel, withWarehouse }: Props) {
  const lookups = useLookups();
  const customers = useCustomerOptions();
  const warehouses = (lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }));

  return (
    <>
      <Row gutter={16}>
        <Col xs={24} md={withWarehouse ? 9 : 12}>
          <Form.Item name="customer_id" label="Customer" rules={[{ required: true, message: 'Choose a customer' }]}>
            <Select showSearch={{ optionFilterProp: 'label' }} options={customers.options} loading={customers.loading} placeholder="Search customer" />
          </Form.Item>
        </Col>
        {withWarehouse && (
          <Col xs={24} md={7}>
            <Form.Item name="warehouse_id" label="Deliver from" rules={[{ required: true, message: 'Choose a warehouse' }]}>
              <Select options={warehouses} loading={lookups.isPending} />
            </Form.Item>
          </Col>
        )}
        <Col xs={12} md={withWarehouse ? 4 : 6}>
          <Form.Item name="date" label={dateLabel} rules={[{ required: true }]}>
            <DatePicker allowClear={false} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={12} md={withWarehouse ? 4 : 6}>
          <Form.Item name="second_date" label={secondDateLabel}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item noStyle dependencies={['customer_id']}>
        {({ getFieldValue }) => <PartyDue kind="customers" id={getFieldValue('customer_id')} />}
      </Form.Item>
      <Form.Item noStyle dependencies={['warehouse_id']}>
        {({ getFieldValue }) => (
          <Form.Item name="items" label="Products" rules={[{ validator: validateLines }]}>
            <DocLineItems priceLabel="Unit price" priceScale={2} availableIn={withWarehouse ? getFieldValue('warehouse_id') : undefined} />
          </Form.Item>
        )}
      </Form.Item>
      <Row gutter={16} align="top">
        <Col xs={24} md={12}>
          <Form.Item name="notes" label="Notes" rules={[{ max: 1000 }]}>
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name="discount"
            label="Discount"
            dependencies={['items']}
            rules={[
              ({ getFieldValue }) => ({
                validator: (_, v) =>
                  v && compare(v, linesTotal(getFieldValue('items'))) > 0
                    ? Promise.reject(new Error('Discount cannot exceed the subtotal'))
                    : Promise.resolve(),
              }),
            ]}
          >
            <InputNumber<string> stringMode min="0" precision={2} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) => {
              const subtotal = linesTotal(getFieldValue('items'));
              const total = subtract(subtotal, getFieldValue('discount') || '0', 2);
              return (
                <Descriptions
                  size="small"
                  column={1}
                  items={[
                    { label: 'Subtotal', children: formatDecimal(subtotal, 2) },
                    { label: 'Discount', children: formatDecimal(getFieldValue('discount') || '0', 2) },
                    { label: <strong>Total</strong>, children: <strong>{formatDecimal(total, 2)}</strong> },
                  ]}
                />
              );
            }}
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}
