import { Form, Input, Typography } from 'antd';

import { MASTER } from '../../api/master';
import type { UnitRecord } from '../../api/master';
import CrudPage from '../../components/CrudPage';

export default function UnitsPage() {
  return (
    <CrudPage<UnitRecord, { name: string; short_code: string }>
      title="Units"
      endpoint={MASTER.units}
      permission="unit"
      itemName="unit"
      searchPlaceholder="Search name or code"
      formMode="modal"
      invalidates={[MASTER.lookups, MASTER.products]}
      errorFields={{ NAME_TAKEN: 'name', SHORT_CODE_TAKEN: 'short_code' }}
      columns={[
        { title: 'Name', dataIndex: 'name' },
        { title: 'Short code', dataIndex: 'short_code', render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
      ]}
      renderForm={() => (
        <>
          <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 50 }]}>
            <Input placeholder="e.g. Kilogram" />
          </Form.Item>
          <Form.Item
            name="short_code"
            label="Short code"
            rules={[
              { required: true, message: 'Enter a short code' },
              { pattern: /^[A-Za-z0-9.]{1,10}$/, message: 'Up to 10 letters, digits or dots' },
            ]}
          >
            <Input placeholder="e.g. KG" />
          </Form.Item>
        </>
      )}
    />
  );
}
