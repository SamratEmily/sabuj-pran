import { FileTextOutlined } from '@ant-design/icons';
import { Button, Col, Form, Input, InputNumber, Row, Tooltip, Typography } from 'antd';
import { useNavigate } from 'react-router';

import { PARTY_ENDPOINT } from '../../api/parties';
import type { PartyKind, PartyRecord } from '../../api/parties';
import CrudPage from '../../components/CrudPage';
import MoneyText from '../../components/MoneyText';
import { usePermission } from '../../hooks/usePermission';

type PartyForm = Omit<PartyRecord, 'id' | 'is_active' | 'due' | 'has_transactions' | 'created_at'>;

const CONFIG = {
  customers: { title: 'Customers', item: 'customer', permission: 'customer', codeHint: 'CUS-0001', dueLabel: 'Due', dueHelp: 'Amount the customer owes us' },
  suppliers: { title: 'Suppliers', item: 'supplier', permission: 'supplier', codeHint: 'SUP-0001', dueLabel: 'Payable', dueHelp: 'Amount we owe the supplier' },
} as const;

export default function PartiesPage({ kind }: { kind: PartyKind }) {
  const cfg = CONFIG[kind];
  const navigate = useNavigate();
  const canStatement = usePermission('party_statement.view');

  return (
    <CrudPage<PartyRecord, PartyForm>
      // Remount when switching between Customers and Suppliers.
      key={kind}
      title={cfg.title}
      endpoint={PARTY_ENDPOINT[kind]}
      permission={cfg.permission}
      itemName={cfg.item}
      searchPlaceholder="Name, code, mobile or contact"
      formWidth={620}
      initialValues={{ opening_due: '0', contact_person: '', address: '', notes: '' }}
      errorFields={{ CODE_TAKEN: 'code', OPENING_LOCKED: 'opening_due' }}
      toFormValues={(p) => ({
        code: p.code,
        name: p.name,
        contact_person: p.contact_person,
        mobile: p.mobile,
        email: p.email,
        address: p.address,
        opening_due: p.opening_due,
        notes: p.notes,
      })}
      columns={[
        { title: 'Code', dataIndex: 'code', width: 110, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
        { title: 'Name', dataIndex: 'name' },
        {
          title: 'Contact',
          key: 'contact',
          render: (_, p) => (
            <>
              <div>{p.contact_person || '—'}</div>
              <Typography.Text type="secondary">{p.mobile}</Typography.Text>
            </>
          ),
        },
        { title: 'Address', dataIndex: 'address', ellipsis: true, render: (v: string) => v || '—' },
        {
          title: (
            <Tooltip title={cfg.dueHelp}>
              <span style={{ display: 'block', textAlign: 'right' }}>{cfg.dueLabel}</span>
            </Tooltip>
          ),
          dataIndex: 'due',
          render: (v: string) => <MoneyText value={v} strong signed />,
        },
      ]}
      rowActions={(p) =>
        canStatement && (
          <Tooltip title="Statement">
            <Button
              size="small"
              type="text"
              icon={<FileTextOutlined />}
              aria-label="Statement"
              onClick={() => navigate(`${PARTY_ENDPOINT[kind]}/${p.id}/statement`)}
            />
          </Tooltip>
        )
      }
      renderForm={({ record }) => (
        <Row gutter={16}>
          <Col xs={24} md={9}>
            <Form.Item
              name="code"
              label="Code"
              extra={record ? undefined : `Leave blank to generate (${cfg.codeHint}…).`}
              rules={[{ pattern: /^[A-Za-z0-9/_.-]{1,20}$/, message: 'Up to 20 letters, digits, / _ . -' }]}
            >
              <Input placeholder={record ? undefined : 'Auto'} />
            </Form.Item>
          </Col>
          <Col xs={24} md={15}>
            <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 150 }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="contact_person" label="Contact person" rules={[{ max: 100 }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="mobile" label="Mobile" rules={[{ pattern: /^\+?[0-9]{6,19}$/, message: 'Digits only, optionally starting with +' }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item name="email" label="Email" rules={[{ type: 'email', message: 'Enter a valid email' }, { max: 150 }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item name="address" label="Address" rules={[{ max: 500 }]}>
              <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item
              name="opening_due"
              label={`Opening ${cfg.dueLabel.toLowerCase()}`}
              extra={
                record?.has_transactions
                  ? 'Locked: this party already has transactions.'
                  : `${cfg.dueHelp} before using this system.`
              }
              rules={[{ required: true, message: 'Enter 0 if none' }]}
            >
              <InputNumber<string> stringMode min="0" precision={2} style={{ width: '100%' }} disabled={record?.has_transactions} />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item name="notes" label="Notes" rules={[{ max: 1000 }]}>
              <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
            </Form.Item>
          </Col>
        </Row>
      )}
    />
  );
}

export function CustomersPage() {
  return <PartiesPage kind="customers" />;
}

export function SuppliersPage() {
  return <PartiesPage kind="suppliers" />;
}
