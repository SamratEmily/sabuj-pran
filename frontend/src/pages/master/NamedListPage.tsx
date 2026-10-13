import { Form, Input } from 'antd';

import { MASTER } from '../../api/master';
import type { NamedRecord } from '../../api/master';
import CrudPage from '../../components/CrudPage';

interface Props {
  title: string;
  endpoint: string;
  permission: string;
  itemName: string;
}

/** Master tables that only have a name (expense / income categories). */
export default function NamedListPage({ title, endpoint, permission, itemName }: Props) {
  return (
    <CrudPage<NamedRecord, { name: string }>
      title={title}
      endpoint={endpoint}
      permission={permission}
      itemName={itemName}
      formMode="modal"
      invalidates={[MASTER.lookups]}
      errorFields={{ NAME_TAKEN: 'name' }}
      columns={[{ title: 'Name', dataIndex: 'name' }]}
      renderForm={() => (
        <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 100 }]}>
          <Input />
        </Form.Item>
      )}
    />
  );
}

export function ExpenseCategoriesPage() {
  return <NamedListPage title="Expense Categories" endpoint={MASTER.expenseCategories} permission="expense_category" itemName="expense category" />;
}

export function IncomeCategoriesPage() {
  return <NamedListPage title="Income Categories" endpoint={MASTER.incomeCategories} permission="income_category" itemName="income category" />;
}
