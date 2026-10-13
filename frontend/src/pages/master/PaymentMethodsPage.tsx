import { Form, Input, Select, Tag } from 'antd';

import { MASTER, METHOD_TYPE_LABELS } from '../../api/master';
import type { MethodType, PaymentMethodRecord } from '../../api/master';
import CrudPage from '../../components/CrudPage';

const TYPE_OPTIONS = Object.entries(METHOD_TYPE_LABELS).map(([value, label]) => ({ value, label }));
const TYPE_COLORS: Record<MethodType, string> = { cash: 'green', bank: 'blue', mfs: 'magenta', online: 'purple' };

export default function PaymentMethodsPage() {
  return (
    <CrudPage<PaymentMethodRecord, { name: string; method_type: MethodType }>
      title="Payment Methods"
      endpoint={MASTER.paymentMethods}
      permission="payment_method"
      itemName="payment method"
      formMode="modal"
      invalidates={[MASTER.lookups]}
      errorFields={{ NAME_TAKEN: 'name' }}
      columns={[
        { title: 'Name', dataIndex: 'name' },
        {
          title: 'Type',
          dataIndex: 'method_type',
          render: (t: MethodType) => <Tag color={TYPE_COLORS[t]}>{METHOD_TYPE_LABELS[t]}</Tag>,
        },
      ]}
      renderForm={() => (
        <>
          <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 100 }]}>
            <Input placeholder="e.g. bKash" />
          </Form.Item>
          <Form.Item name="method_type" label="Type" rules={[{ required: true, message: 'Choose a type' }]}>
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
        </>
      )}
    />
  );
}
