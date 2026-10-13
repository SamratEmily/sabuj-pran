import { Alert, Form, InputNumber, Select } from 'antd';

import { ADMIN } from '../../api/admin';
import type { RoleRecord } from '../../api/admin';
import { APPROVALS, DOCUMENT_TYPE_OPTIONS } from '../../api/approvals';
import type { ApprovalRule, DocumentType } from '../../api/approvals';
import CrudPage from '../../components/CrudPage';
import MoneyText from '../../components/MoneyText';
import { useList } from '../../hooks/useApi';

interface RuleForm {
  document_type: DocumentType;
  min_amount: string;
  approver_role_id: number;
}

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

export default function ApprovalRulesPage() {
  const roles = useList<RoleRecord>(ADMIN.roles, { page_size: 100 });
  const roleOptions = (roles.data?.items ?? []).map((r) => ({ label: r.name, value: r.id }));
  return (
    <CrudPage<ApprovalRule, RuleForm>
      title="Approval Rules"
      endpoint={APPROVALS.rules}
      permission="approval_rule"
      itemName="rule"
      searchPlaceholder="Document or approver role"
      formMode="modal"
      filters={[{ name: 'document_type', label: 'Document', options: DOCUMENT_TYPE_OPTIONS, width: 200 }]}
      headerExtra={
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="A document needs approval when its amount is at least the minimum of an active rule. If several rules match, the one with the highest minimum decides the approver role."
        />
      }
      errorFields={{ INVALID_ROLE: 'approver_role_id' }}
      toFormValues={(r) => ({ document_type: r.document_type, min_amount: r.min_amount, approver_role_id: r.approver_role_id })}
      columns={[
        { title: 'Document', dataIndex: 'document_label' },
        { title: right('Minimum amount'), dataIndex: 'min_amount', render: (v: string) => <MoneyText value={v} strong /> },
        { title: 'Approver role', dataIndex: 'approver_role_name' },
      ]}
      renderForm={() => (
        <>
          <Form.Item name="document_type" label="Document" rules={[{ required: true, message: 'Choose the document type' }]}>
            <Select options={DOCUMENT_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="min_amount" label="Needs approval from (amount)" rules={[{ required: true, message: 'Enter the minimum amount' }]}>
            <InputNumber<string> stringMode min="0" precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="approver_role_id" label="Approver role" rules={[{ required: true, message: 'Choose the role' }]}>
            <Select options={roleOptions} loading={roles.isPending} />
          </Form.Item>
        </>
      )}
    />
  );
}
