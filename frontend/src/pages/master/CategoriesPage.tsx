import { Form, Input } from 'antd';

import { MASTER } from '../../api/master';
import type { Category } from '../../api/master';
import CrudPage from '../../components/CrudPage';

export default function CategoriesPage() {
  return (
    <CrudPage<Category, { name: string; description: string }>
      title="Product Categories"
      endpoint={MASTER.categories}
      permission="category"
      itemName="category"
      searchPlaceholder="Search name or description"
      formMode="modal"
      invalidates={[MASTER.lookups, MASTER.products]}
      errorFields={{ NAME_TAKEN: 'name' }}
      initialValues={{ description: '' }}
      columns={[
        { title: 'Name', dataIndex: 'name' },
        { title: 'Description', dataIndex: 'description', render: (v: string) => v || '—' },
      ]}
      renderForm={() => (
        <>
          <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 100 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="Description" rules={[{ max: 255 }]}>
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
        </>
      )}
    />
  );
}
