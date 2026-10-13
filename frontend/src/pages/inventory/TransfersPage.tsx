import { DatePicker, Form, Input, Select } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useNavigate } from 'react-router';

import { INVENTORY } from '../../api/inventory';
import type { TransferDoc } from '../../api/inventory';
import { useLookups } from '../../api/master';
import CrudPage from '../../components/CrudPage';
import DocLineItems, { newLine, validateQtyLines } from '../../components/DocLineItems';
import type { DocLine } from '../../components/DocLineItems';
import { dateColumn, numberColumn, tailColumns } from './docColumns';
import { STATUS_FILTER_OPTIONS } from './labels';

interface TransferForm {
  from_warehouse_id: number;
  to_warehouse_id: number;
  transfer_date: Dayjs;
  note: string;
  items: DocLine[];
}

export default function TransfersPage() {
  const navigate = useNavigate();
  const lookups = useLookups();
  const warehouses = (lookups.data?.warehouses ?? []).map((w) => ({ label: w.name, value: w.id }));
  const defaultWarehouse = lookups.data?.warehouses.find((w) => w.is_default)?.id;

  return (
    <CrudPage<TransferDoc, TransferForm>
      title="Stock Transfers"
      endpoint={INVENTORY.transfers}
      permission="stock_transfer"
      itemName="transfer"
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
      initialValues={{ from_warehouse_id: defaultWarehouse, transfer_date: dayjs(), note: '', items: [newLine({ price: undefined })] }}
      errorFields={{ SAME_WAREHOUSE: 'to_warehouse_id', DUPLICATE_LINE: 'items', INACTIVE_PRODUCT: 'items' }}
      toPayload={(v) => ({
        from_warehouse_id: v.from_warehouse_id,
        to_warehouse_id: v.to_warehouse_id,
        transfer_date: v.transfer_date.format('YYYY-MM-DD'),
        note: v.note ?? '',
        items: v.items.map((l) => ({ product_id: l.product_id, qty: l.qty })),
      })}
      onSaved={(doc) => navigate(`${INVENTORY.transfers}/${doc.id}`)}
      columns={[
        numberColumn(INVENTORY.transfers),
        dateColumn('transfer_date'),
        { title: 'From', dataIndex: 'from_warehouse_name' },
        { title: 'To', dataIndex: 'to_warehouse_name' },
        ...tailColumns,
      ]}
      renderForm={() => (
        <>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <Form.Item name="from_warehouse_id" label="From warehouse" rules={[{ required: true, message: 'Choose the source' }]} style={{ minWidth: 220, flex: 1 }}>
                <Select options={warehouses} loading={lookups.isPending} />
              </Form.Item>
              <Form.Item
                name="to_warehouse_id"
                label="To warehouse"
                dependencies={['from_warehouse_id']}
                rules={[
                  { required: true, message: 'Choose the destination' },
                  ({ getFieldValue }) => ({
                    validator: (_, v) =>
                      v && v === getFieldValue('from_warehouse_id')
                        ? Promise.reject(new Error('Must differ from the source warehouse'))
                        : Promise.resolve(),
                  }),
                ]}
                style={{ minWidth: 220, flex: 1 }}
              >
                <Select options={warehouses} loading={lookups.isPending} />
              </Form.Item>
              <Form.Item name="transfer_date" label="Date" rules={[{ required: true }]}>
                <DatePicker allowClear={false} />
              </Form.Item>
          </div>
          <Form.Item noStyle dependencies={['from_warehouse_id']}>
            {({ getFieldValue }) => (
              <Form.Item name="items" label="Products" rules={[{ validator: validateQtyLines }]}>
                <DocLineItems showPrice={false} availableIn={getFieldValue('from_warehouse_id')} />
              </Form.Item>
            )}
          </Form.Item>
          <Form.Item name="note" label="Note" rules={[{ max: 500 }]}>
            <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
          </Form.Item>
        </>
      )}
    />
  );
}
