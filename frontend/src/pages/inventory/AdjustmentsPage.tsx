import { AutoComplete, DatePicker, Form, Input, InputNumber, Select } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useNavigate } from 'react-router';

import { INVENTORY } from '../../api/inventory';
import type { AdjustmentDoc } from '../../api/inventory';
import { useLookups } from '../../api/master';
import CrudPage from '../../components/CrudPage';
import DocLineItems, { newLine, validateQtyLines } from '../../components/DocLineItems';
import type { DocLine } from '../../components/DocLineItems';
import { dateColumn, numberColumn, tailColumns } from './docColumns';
import { STATUS_FILTER_OPTIONS } from './labels';

interface AdjustmentForm {
  warehouse_id: number;
  adjustment_date: Dayjs;
  reason: string;
  note: string;
  items: DocLine[];
}

const REASONS = ['Opening stock', 'Damaged', 'Expired', 'Found during check', 'Lost / missing', 'Correction'];

export default function AdjustmentsPage() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const warehouses = (lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }));
  const defaultWarehouse = lookups.data?.warehouses.find((w) => w.is_default)?.id;

  return (
    <CrudPage<AdjustmentDoc, AdjustmentForm>
      title="Stock Adjustments"
      endpoint={INVENTORY.adjustments}
      permission="stock_adjustment"
      itemName="adjustment"
      searchPlaceholder="Search number"
      editable={false}
      deactivatable={false}
      saveLabel="Save draft"
      formWidth={1040}
      invalidates={[INVENTORY.stock]}
      filters={[
        { name: 'status', label: 'Status', options: [...STATUS_FILTER_OPTIONS, { label: 'Pending approval', value: 'pending_approval' }, { label: 'Rejected', value: 'rejected' }] },
        { name: 'warehouse_id', label: 'Warehouse', options: warehouses },
      ]}
      initialValues={{
        warehouse_id: defaultWarehouse,
        adjustment_date: dayjs(),
        reason: '',
        note: '',
        items: [newLine({ price: undefined, direction: 'increase' })],
      }}
      errorFields={{ DUPLICATE_LINE: 'items', INACTIVE_PRODUCT: 'items' }}
      toPayload={(v) => ({
        warehouse_id: v.warehouse_id,
        adjustment_date: v.adjustment_date.format('YYYY-MM-DD'),
        reason: v.reason,
        note: v.note ?? '',
        items: v.items.map((l) => ({
          product_id: l.product_id,
          direction: l.direction,
          qty: l.qty,
          unit_cost: l.direction === 'increase' && l.unit_cost ? l.unit_cost : null,
          note: '',
        })),
      })}
      onSaved={(doc) => navigate(`${INVENTORY.adjustments}/${doc.id}`)}
      columns={[
        numberColumn(INVENTORY.adjustments),
        dateColumn('adjustment_date'),
        { title: 'Warehouse', dataIndex: 'warehouse_name' },
        { title: 'Reason', dataIndex: 'reason', ellipsis: true },
        ...tailColumns,
      ]}
      renderForm={() => (
        <>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="warehouse_id" label="Warehouse" rules={[{ required: true, message: 'Choose a warehouse' }]} style={{ minWidth: 220, flex: 1 }}>
              <Select options={warehouses} loading={lookups.isPending} />
            </Form.Item>
            <Form.Item name="adjustment_date" label="Date" rules={[{ required: true }]}>
              <DatePicker allowClear={false} />
            </Form.Item>
            <Form.Item
              name="reason"
              label="Reason"
              rules={[{ required: true, whitespace: true, message: 'Give a reason' }, { max: 255 }]}
              style={{ minWidth: 260, flex: 2 }}
            >
              <AutoComplete options={REASONS.map((r) => ({ value: r }))} placeholder="e.g. Opening stock" />
            </Form.Item>
          </div>
          <Form.Item noStyle dependencies={['warehouse_id']}>
            {({ getFieldValue }) => (
              <Form.Item name="items" label="Products" rules={[{ validator: validateQtyLines }]}>
                <DocLineItems
                  showPrice={false}
                  availableIn={getFieldValue('warehouse_id')}
                  newLineDefaults={{ direction: 'increase' }}
                  extraColumns={[
                    {
                      key: 'direction',
                      title: 'Change',
                      width: 140,
                      render: (line, update) => (
                        <Select
                          value={line.direction as string}
                          onChange={(direction) => update({ direction })}
                          options={[
                            { label: 'Increase (+)', value: 'increase' },
                            { label: 'Decrease (−)', value: 'decrease' },
                          ]}
                          style={{ width: '100%' }}
                          aria-label="Change"
                        />
                      ),
                    },
                    {
                      key: 'unit_cost',
                      title: 'Unit cost',
                      width: 160,
                      render: (line, update) =>
                        line.direction === 'increase' ? (
                          <InputNumber<string>
                            stringMode
                            min="0"
                            precision={4}
                            value={(line.unit_cost as string | null) ?? null}
                            onChange={(unit_cost) => update({ unit_cost })}
                            placeholder="Avg / default"
                            style={{ width: '100%' }}
                            aria-label="Unit cost"
                          />
                        ) : (
                          <span style={{ color: 'var(--ant-color-text-tertiary, #999)' }}>Current avg</span>
                        ),
                    },
                  ]}
                />
              </Form.Item>
            )}
          </Form.Item>
          <Form.Item name="note" label="Note" rules={[{ max: 500 }]} extra="Increases without a cost use the current average cost, or the product's purchase price if it has none.">
            <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
          </Form.Item>
        </>
      )}
    />
  );
}
