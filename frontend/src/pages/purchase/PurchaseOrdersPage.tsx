import { Alert, Checkbox, Col, DatePicker, Descriptions, Form, Input, InputNumber, Row, Select } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { Link, useNavigate } from 'react-router';

import { api } from '../../api/client';

import { INVENTORY } from '../../api/inventory';
import { useLookups } from '../../api/master';
import type { PartyRecord } from '../../api/parties';
import { PURCHASE, purchaseApi } from '../../api/purchase';
import type { PoPayload, PurchaseOrder, PurchaseOrderDetail } from '../../api/purchase';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import DocLineItems, { linesTotal, newLine, validateLines } from '../../components/DocLineItems';
import type { DocLine } from '../../components/DocLineItems';
import MoneyText from '../../components/MoneyText';
import StatusTag from '../../components/StatusTag';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { compare, formatDecimal, subtract } from '../../utils/decimal';

interface PoForm {
  supplier_id: number;
  warehouse_id: number;
  order_date: Dayjs;
  expected_date?: Dayjs | null;
  discount?: string | null;
  notes?: string;
  items: DocLine[];
  direct?: boolean;
}

const STATUS_OPTIONS = [
  { label: 'Draft', value: 'draft' },
  { label: 'Pending approval', value: 'pending_approval' },
  { label: 'Approved', value: 'approved' },
  { label: 'Partially received', value: 'partially_received' },
  { label: 'Received', value: 'received' },
  { label: 'Cancelled', value: 'cancelled' },
  { label: 'Rejected', value: 'rejected' },
];

function toPayload(v: PoForm): PoPayload {
  return {
    supplier_id: v.supplier_id,
    warehouse_id: v.warehouse_id,
    order_date: v.order_date.format('YYYY-MM-DD'),
    expected_date: v.expected_date ? v.expected_date.format('YYYY-MM-DD') : null,
    discount: v.discount || '0',
    notes: v.notes ?? '',
    items: v.items.map((l) => ({ product_id: l.product_id!, qty: l.qty!, unit_cost: l.price! })),
  };
}

export default function PurchaseOrdersPage() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const suppliers = useList<PartyRecord>('/suppliers', { page_size: 100, is_active: true });
  const canReceive = usePermission('goods_receipt.create');
  const canCreatePo = usePermission('purchase_order.create');
  const canDirect = canReceive && canCreatePo;
  const supplierOptions = (suppliers.data?.items ?? []).map((s) => ({ label: `${s.code} ${s.name}`, value: s.id }));
  const warehouses = (lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }));
  const defaultWarehouse = lookups.data?.warehouses.find((w) => w.is_default)?.id;

  return (
    <CrudPage<PurchaseOrder, PoForm>
      title="Purchase Orders"
      endpoint={PURCHASE.orders}
      permission="purchase_order"
      itemName="purchase order"
      searchPlaceholder="PO number or supplier"
      deactivatable={false}
      canEditRow={(po) => po.status === 'draft'}
      saveLabel="Save"
      formWidth={1080}
      invalidates={[INVENTORY.stock, PURCHASE.receipts, '/suppliers']}
      filters={[
        { name: 'supplier_id', label: 'Supplier', options: supplierOptions, width: 220 },
        { name: 'status', label: 'Status', options: STATUS_OPTIONS },
      ]}
      initialValues={{
        warehouse_id: defaultWarehouse,
        order_date: dayjs(),
        discount: '0',
        notes: '',
        items: [newLine()],
        direct: false,
      }}
      errorFields={{
        INACTIVE_SUPPLIER: 'supplier_id',
        INVALID_SUPPLIER: 'supplier_id',
        INACTIVE_WAREHOUSE: 'warehouse_id',
        INVALID_DISCOUNT: 'discount',
        DUPLICATE_LINE: 'items',
        INACTIVE_PRODUCT: 'items',
      }}
      toFormValues={(po) => ({
        supplier_id: po.supplier_id,
        warehouse_id: po.warehouse_id,
        order_date: dayjs(po.order_date),
        expected_date: po.expected_date ? dayjs(po.expected_date) : null,
        discount: po.discount,
        notes: po.notes,
        items: po.items.map((i) =>
          newLine({ product_id: i.product_id, product_name: `${i.product_code} ${i.product_name}`, qty: i.qty, price: i.unit_cost }),
        ),
      })}
      // The "direct purchase" box posts to a different endpoint that also receives the goods.
      toPayload={(v) => ({ ...toPayload(v), direct: !!v.direct })}
      submit={async (data, record) => {
        const { direct, ...payload } = data as PoPayload & { direct: boolean };
        if (!record && direct) return purchaseApi.direct(payload);
        const res = record
          ? await api.put<PurchaseOrderDetail>(`${PURCHASE.orders}/${record.id}`, payload)
          : await api.post<PurchaseOrderDetail>(PURCHASE.orders, payload);
        return res.data;
      }}
      onSaved={(po) => navigate(`${PURCHASE.orders}/${po.id}`)}
      columns={[
        {
          title: 'PO',
          key: 'number',
          render: (_, po) => <Link to={`${PURCHASE.orders}/${po.id}`}><strong>{po.po_number}</strong></Link>,
        },
        { title: 'Date', dataIndex: 'order_date', render: (v: string) => <DateText value={v} /> },
        { title: 'Supplier', dataIndex: 'supplier_name' },
        { title: 'Warehouse', dataIndex: 'warehouse_name' },
        { title: <span style={{ display: 'block', textAlign: 'right' }}>Total</span>, dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
        { title: 'Status', dataIndex: 'status', render: (s: string) => <StatusTag status={s} /> },
      ]}
      renderForm={({ record }) => (
        <>
          <Row gutter={16}>
            <Col xs={24} md={9}>
              <Form.Item name="supplier_id" label="Supplier" rules={[{ required: true, message: 'Choose a supplier' }]}>
                <Select showSearch={{ optionFilterProp: 'label' }} options={supplierOptions} loading={suppliers.isPending} placeholder="Search supplier" />
              </Form.Item>
            </Col>
            <Col xs={24} md={7}>
              <Form.Item name="warehouse_id" label="Receive into" rules={[{ required: true, message: 'Choose a warehouse' }]}>
                <Select options={warehouses} loading={lookups.isPending} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="order_date" label="Order date" rules={[{ required: true }]}>
                <DatePicker allowClear={false} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="expected_date" label="Expected">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="items" label="Products" rules={[{ validator: validateLines }]}>
            <DocLineItems priceLabel="Unit cost" priceScale={4} defaultPrice={(p) => p.purchase_price as string} />
          </Form.Item>
          <Row gutter={16} align="top">
            <Col xs={24} md={12}>
              <Form.Item name="notes" label="Notes" rules={[{ max: 1000 }]}>
                <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
              </Form.Item>
              {!record && canDirect && (
                <Form.Item name="direct" valuePropName="checked" style={{ marginBottom: 0 }}>
                  <Checkbox>Direct purchase: receive immediately</Checkbox>
                </Form.Item>
              )}
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="discount"
                label="Discount (bill only)"
                dependencies={['items']}
                extra="Reduces the amount owed to the supplier; stock keeps the line cost."
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
                        { label: <strong>Total payable</strong>, children: <strong>{formatDecimal(total, 2)}</strong> },
                      ]}
                    />
                  );
                }}
              </Form.Item>
            </Col>
          </Row>
          <Form.Item noStyle shouldUpdate={(a, b) => a.direct !== b.direct}>
            {({ getFieldValue }) =>
              getFieldValue('direct') ? (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 12 }}
                  title="Saving will create the order, receive every line into stock and credit the supplier, in one step."
                />
              ) : null
            }
          </Form.Item>
        </>
      )}
    />
  );
}
