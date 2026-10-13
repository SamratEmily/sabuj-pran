import { Checkbox, Form, Input, Tag, Typography } from 'antd';

import { MASTER } from '../../api/master';
import type { WarehouseRecord } from '../../api/master';
import CrudPage from '../../components/CrudPage';

type WarehouseForm = Omit<WarehouseRecord, 'id' | 'is_active'>;

export default function WarehousesPage() {
  return (
    <CrudPage<WarehouseRecord, WarehouseForm>
      title="Warehouses"
      endpoint={MASTER.warehouses}
      permission="warehouse"
      itemName="warehouse"
      searchPlaceholder="Search name or code"
      invalidates={[MASTER.lookups]}
      initialValues={{ address: '', is_default: false }}
      errorFields={{ NAME_TAKEN: 'name', CODE_TAKEN: 'code', DEFAULT_REQUIRED: 'is_default', INACTIVE_DEFAULT: 'is_default' }}
      toFormValues={(w) => ({ name: w.name, code: w.code, address: w.address, is_default: w.is_default })}
      columns={[
        {
          title: 'Name',
          key: 'name',
          render: (_, w) => (
            <>
              {w.name} {w.is_default && <Tag color="gold">Default</Tag>}
            </>
          ),
        },
        { title: 'Code', dataIndex: 'code', render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
        { title: 'Address', dataIndex: 'address', render: (v: string) => v || '—' },
      ]}
      renderForm={({ record }) => (
        <>
          <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 100 }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="code"
            label="Code"
            rules={[
              { required: true, message: 'Enter a code' },
              { pattern: /^[A-Za-z0-9/_.-]{1,20}$/, message: 'Up to 20 letters, digits, / _ . -' },
            ]}
          >
            <Input placeholder="e.g. MAIN" />
          </Form.Item>
          <Form.Item name="address" label="Address" rules={[{ max: 500 }]}>
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
          <Form.Item
            name="is_default"
            valuePropName="checked"
            extra={
              record?.is_default
                ? 'This is the default warehouse. To change it, make another warehouse the default.'
                : 'Exactly one warehouse is the default; choosing this one replaces the current default.'
            }
          >
            <Checkbox disabled={record?.is_default}>Default warehouse</Checkbox>
          </Form.Item>
        </>
      )}
    />
  );
}
