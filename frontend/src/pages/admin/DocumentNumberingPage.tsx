import { Form, Input, InputNumber, Typography } from 'antd';

import { ADMIN } from '../../api/admin';
import type { DocumentSequence } from '../../api/admin';
import CrudPage from '../../components/CrudPage';

interface SequenceForm {
  prefix: string;
  padding: number;
  next_number: number;
}

function preview(v: Partial<SequenceForm>): string {
  if (!v.padding || !v.next_number) return '';
  return `${v.prefix ?? ''}${String(v.next_number).padStart(v.padding, '0')}`;
}

export default function DocumentNumberingPage() {
  return (
    <CrudPage<DocumentSequence, SequenceForm>
      title="Document Numbering"
      endpoint={ADMIN.sequences}
      permission="document_sequence"
      itemName="sequence"
      creatable={false}
      deactivatable={false}
      searchable={false}
      formMode="modal"
      errorFields={{ SEQUENCE_DECREASE: 'next_number' }}
      toFormValues={(s) => ({ prefix: s.prefix, padding: s.padding, next_number: s.next_number })}
      columns={[
        { title: 'Document', dataIndex: 'label' },
        { title: 'Code', dataIndex: 'doc_type', render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
        { title: 'Prefix', dataIndex: 'prefix', render: (v: string) => v || '—' },
        { title: 'Digits', dataIndex: 'padding', align: 'right' },
        { title: 'Next number', dataIndex: 'next_number', align: 'right' },
        { title: 'Next document', dataIndex: 'preview', render: (v: string) => <Typography.Text strong>{v}</Typography.Text> },
      ]}
      renderForm={({ record }) => (
        <>
          <Typography.Paragraph type="secondary">
            {record?.label} numbers. Changes apply to the next document created.
          </Typography.Paragraph>
          <Form.Item
            name="prefix"
            label="Prefix"
            rules={[
              { max: 20 },
              { pattern: /^[A-Za-z0-9/_-]*$/, message: 'Letters, digits, / _ - only' },
            ]}
          >
            <Input placeholder="e.g. INV-" />
          </Form.Item>
          <Form.Item name="padding" label="Digits" rules={[{ required: true, message: 'Enter the number of digits' }]}>
            <InputNumber min={1} max={12} precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="next_number"
            label="Next number"
            extra={record ? `Can only be raised (currently ${record.next_number}), so numbers never repeat.` : undefined}
            rules={[{ required: true, message: 'Enter the next number' }]}
          >
            <InputNumber min={record?.next_number ?? 1} max={2_000_000_000} precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldsValue }) => (
              <Typography.Paragraph>
                Next document will be: <Typography.Text strong>{preview(getFieldsValue()) || '—'}</Typography.Text>
              </Typography.Paragraph>
            )}
          </Form.Item>
        </>
      )}
    />
  );
}
