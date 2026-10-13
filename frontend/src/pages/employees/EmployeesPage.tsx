import { Col, DatePicker, Form, Input, InputNumber, Row, Select } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';

import { ADMIN } from '../../api/admin';
import type { AdminUser } from '../../api/admin';
import { EMPLOYEES } from '../../api/employees';
import type { EmployeeRecord } from '../../api/employees';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';

interface EmployeeForm {
  code?: string;
  full_name: string;
  mobile?: string;
  email?: string;
  designation?: string;
  department?: string;
  joining_date?: Dayjs | null;
  base_salary?: string;
  user_id?: number | null;
}

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

export default function EmployeesPage() {
  const canSeeUsers = usePermission('user.view');
  const users = useList<AdminUser>(ADMIN.users, { page_size: 100 }, canSeeUsers);
  return (
    <CrudPage<EmployeeRecord, EmployeeForm>
      title="Employees"
      endpoint={EMPLOYEES.list}
      permission="employee"
      itemName="employee"
      searchPlaceholder="Code, name, mobile or designation"
      formWidth={640}
      initialValues={{ base_salary: '0' }}
      errorFields={{ CODE_TAKEN: 'code', USER_TAKEN: 'user_id', INVALID_USER: 'user_id' }}
      toFormValues={(e) => ({ ...e, joining_date: e.joining_date ? dayjs(e.joining_date) : null })}
      toPayload={(v) => ({ ...v, joining_date: v.joining_date ? v.joining_date.format('YYYY-MM-DD') : null, user_id: v.user_id ?? null })}
      columns={[
        { title: 'Code', dataIndex: 'code', render: (v: string) => <strong>{v}</strong> },
        { title: 'Name', dataIndex: 'full_name' },
        { title: 'Designation', dataIndex: 'designation', render: (v: string) => v || '—' },
        { title: 'Department', dataIndex: 'department', render: (v: string) => v || '—' },
        { title: 'Mobile', dataIndex: 'mobile', render: (v: string) => v || '—' },
        { title: 'Joined', dataIndex: 'joining_date', render: (v: string | null) => <DateText value={v} /> },
        { title: right('Base salary'), dataIndex: 'base_salary', render: (v: string) => <MoneyText value={v} /> },
        { title: 'Login', dataIndex: 'username', render: (v: string | null) => v ?? '—' },
      ]}
      renderForm={({ record }) => (
        <>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="code" label="Code" extra={record ? undefined : 'Blank = next EMP number'} rules={[{ max: 20 }]}>
                <Input placeholder="EMP-0001" />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item name="full_name" label="Full name" rules={[{ required: true, message: 'Enter the name' }, { max: 150 }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="designation" label="Designation" rules={[{ max: 100 }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="department" label="Department" rules={[{ max: 100 }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="mobile" label="Mobile">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="email" label="Email" rules={[{ type: 'email' }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="joining_date" label="Joining date">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="base_salary" label="Base salary (monthly)" rules={[{ required: true, message: 'Enter the salary' }]}>
                <InputNumber<string> stringMode min="0" precision={2} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          {canSeeUsers && (
            <Form.Item name="user_id" label="Login account (optional)">
              <Select
                allowClear
                showSearch={{ optionFilterProp: 'label' }}
                loading={users.isPending}
                options={(users.data?.items ?? []).map((u) => ({ value: u.id, label: `${u.full_name} (${u.username})` }))}
              />
            </Form.Item>
          )}
        </>
      )}
    />
  );
}
