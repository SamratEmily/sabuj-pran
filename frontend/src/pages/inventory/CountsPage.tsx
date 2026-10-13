import { CloudDownloadOutlined } from '@ant-design/icons';
import { App, Button, DatePicker, Flex, Form, Input, Select, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { INVENTORY, inventoryApi, useStockOf } from '../../api/inventory';
import type { CountDoc } from '../../api/inventory';
import { useLookups } from '../../api/master';
import CrudPage from '../../components/CrudPage';
import DocLineItems, { newLine, validateCountLines } from '../../components/DocLineItems';
import type { DocLine } from '../../components/DocLineItems';
import QtyText from '../../components/QtyText';
import { compare, subtract } from '../../utils/decimal';
import { notifyError } from '../../utils/notify';
import { dateColumn, numberColumn, tailColumns } from './docColumns';
import { STATUS_FILTER_OPTIONS } from './labels';

interface CountForm {
  warehouse_id: number;
  count_date: Dayjs;
  note: string;
  items: DocLine[];
}

/** System qty of a line: the value loaded with the warehouse, else the live on-hand. */
function useSystemQty(line: DocLine, warehouseId?: number): string | undefined {
  const known = line.system_qty as string | undefined;
  const stock = useStockOf(line.product_id, warehouseId, known === undefined);
  if (known !== undefined) return known;
  if (!line.product_id || stock.isPending) return undefined;
  return stock.data?.qty_on_hand ?? '0';
}

function SystemQtyCell({ line, warehouseId }: { line: DocLine; warehouseId?: number }) {
  const system = useSystemQty(line, warehouseId);
  return system === undefined ? null : <QtyText value={system} />;
}

/** Counted - system, highlighted: red = shortage, green = surplus. */
function VarianceCell({ line, warehouseId }: { line: DocLine; warehouseId?: number }) {
  const system = useSystemQty(line, warehouseId);
  if (system === undefined || line.qty === null || line.qty === undefined || line.qty === '') return null;
  const variance = subtract(line.qty, system, 3);
  const sign = compare(variance, 0);
  if (sign === 0) return <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'right' }}>0</Typography.Text>;
  return (
    <div style={{ textAlign: 'right' }}>
      <Tag color={sign < 0 ? 'red' : 'green'} style={{ marginInlineEnd: 0, fontWeight: 600 }}>
        {sign > 0 ? '+' : ''}
        {Number(variance).toLocaleString(undefined, { maximumFractionDigits: 3 })}
      </Tag>
    </div>
  );
}

export default function CountsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const lookups = useLookups();
  const [loading, setLoading] = useState(false);
  const warehouses = (lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }));
  const defaultWarehouse = lookups.data?.warehouses.find((w) => w.is_default)?.id;

  return (
    <CrudPage<CountDoc, CountForm>
      title="Physical Count"
      endpoint={INVENTORY.counts}
      permission="stock_count"
      itemName="count"
      searchPlaceholder="Search number"
      editable={false}
      deactivatable={false}
      saveLabel="Save draft"
      formWidth={980}
      invalidates={[INVENTORY.stock]}
      filters={[
        { name: 'status', label: 'Status', options: STATUS_FILTER_OPTIONS },
        { name: 'warehouse_id', label: 'Warehouse', options: warehouses },
      ]}
      initialValues={{ warehouse_id: defaultWarehouse, count_date: dayjs(), note: '', items: [] }}
      errorFields={{ DUPLICATE_LINE: 'items', INACTIVE_PRODUCT: 'items' }}
      toPayload={(v) => ({
        warehouse_id: v.warehouse_id,
        count_date: v.count_date.format('YYYY-MM-DD'),
        note: v.note ?? '',
        items: v.items.map((l) => ({ product_id: l.product_id, counted_qty: l.qty })),
      })}
      onSaved={(doc) => navigate(`${INVENTORY.counts}/${doc.id}`)}
      columns={[
        numberColumn(INVENTORY.counts),
        dateColumn('count_date'),
        { title: 'Warehouse', dataIndex: 'warehouse_name' },
        ...tailColumns,
      ]}
      renderForm={({ form }) => (
        <>
          <Flex gap={16} wrap align="flex-end">
            <Form.Item name="warehouse_id" label="Warehouse" rules={[{ required: true, message: 'Choose a warehouse' }]} style={{ minWidth: 220, flex: 1 }}>
              {/* System quantities belong to one warehouse: changing it clears the lines. */}
              <Select options={warehouses} loading={lookups.isPending} onChange={() => form.setFieldValue('items', [])} />
            </Form.Item>
            <Form.Item name="count_date" label="Count date" rules={[{ required: true }]}>
              <DatePicker allowClear={false} />
            </Form.Item>
            <Form.Item>
              <Button
                icon={<CloudDownloadOutlined />}
                loading={loading}
                onClick={async () => {
                  const warehouseId = form.getFieldValue('warehouse_id') as number | undefined;
                  if (!warehouseId) return;
                  setLoading(true);
                  try {
                    const rows = await inventoryApi.allStockIn(warehouseId);
                    form.setFieldValue(
                      'items',
                      rows.map((r) =>
                        newLine({
                          product_id: r.product_id,
                          product_name: `${r.product_code} ${r.product_name}`,
                          system_qty: r.qty_on_hand,
                          qty: r.qty_on_hand, // start from the system qty; edit what differs
                          price: undefined,
                        }),
                      ),
                    );
                    message.info(rows.length ? `Loaded ${rows.length} stocked products` : 'No stock in this warehouse yet');
                  } catch (error) {
                    notifyError(error, 'Could not load stock');
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Load system quantities
              </Button>
            </Form.Item>
          </Flex>
          <Form.Item noStyle dependencies={['warehouse_id']}>
            {({ getFieldValue }) => {
              const warehouseId = getFieldValue('warehouse_id') as number | undefined;
              return (
                <Form.Item
                  name="items"
                  label="Counted products"
                  extra="Enter what you physically counted. The system quantity is snapshotted when you save; posting applies the variance."
                  rules={[{ validator: validateCountLines }]}
                >
                  <DocLineItems
                    showPrice={false}
                    qtyLabel="Counted qty"
                    newLineDefaults={{ qty: null }}
                    extraColumns={[
                      {
                        key: 'system',
                        title: <span style={{ display: 'block', textAlign: 'right' }}>System qty</span>,
                        width: 120,
                        render: (line) => <SystemQtyCell line={line} warehouseId={warehouseId} />,
                      },
                      {
                        key: 'variance',
                        title: <span style={{ display: 'block', textAlign: 'right' }}>Variance</span>,
                        width: 120,
                        afterQty: true,
                        render: (line) => <VarianceCell line={line} warehouseId={warehouseId} />,
                      },
                    ]}
                  />
                </Form.Item>
              );
            }}
          </Form.Item>
          <Form.Item name="note" label="Note" rules={[{ max: 500 }]}>
            <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
          </Form.Item>
        </>
      )}
    />
  );
}
