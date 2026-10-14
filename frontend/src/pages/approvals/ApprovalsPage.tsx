import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, DatePicker, Flex, Input, Modal, Select, Tabs, Tooltip, Typography } from 'antd';
import type { TableProps } from 'antd';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';
import { Link } from 'react-router';

import { errorMessage } from '../../api/client';
import { APPROVALS, DOCUMENT_TYPE_OPTIONS, approvalsApi, documentLink } from '../../api/approvals';
import type { ApprovalRequest } from '../../api/approvals';
import DateText from '../../components/DateText';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import PagedTable from '../../components/PagedTable';
import StatusTag from '../../components/StatusTag';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { formatDecimal } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

/** Every query that can show a document affected by a decision. */
const AFFECTED = [
  APPROVALS.pending,
  APPROVALS.pendingCount,
  APPROVALS.history,
  '/purchase/orders',
  '/inventory/adjustments',
  '/inventory/stock',
  '/money/expenses',
  '/money/supplier-payments',
  '/money/accounts',
  '/suppliers',
];

function DecisionModal({ target, onClose }: { target: { approval: ApprovalRequest; decision: 'approve' | 'reject' } | null; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [remark, setRemark] = useState('');
  const mutation = useMutation({
    mutationFn: () => approvalsApi.decide(target!.approval.id, target!.decision, remark.trim()),
    meta: { silent: true },
    onSuccess: async (a) => {
      message.success(`${a.document_number} ${a.status}`);
      onClose();
      await Promise.all(AFFECTED.map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
    },
  });
  const approving = target?.decision === 'approve';
  const a = target?.approval;
  return (
    <Modal
      title={a ? `${approving ? 'Approve' : 'Reject'} ${a.document_number}?` : ''}
      open={target !== null}
      onCancel={onClose}
      okText={approving ? 'Approve' : 'Reject'}
      okButtonProps={{ danger: !approving, disabled: !approving && !remark.trim() }}
      confirmLoading={mutation.isPending}
      onOk={() => mutation.mutate()}
      afterOpenChange={(open) => {
        if (open) {
          setRemark('');
          mutation.reset();
        }
      }}
      destroyOnHidden
    >
      {mutation.isError && <Alert type="error" showIcon title="Could not record the decision" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />}
      {a && (
        <Typography.Paragraph>
          {a.document_label} <strong>{a.document_number}</strong> for <strong>{formatDecimal(a.amount, 2)}</strong>, requested by {a.requested_by_name}.{' '}
          {approving ? 'It will be posted now.' : 'Nothing will be posted.'}
        </Typography.Paragraph>
      )}
      <Input.TextArea
        value={remark}
        maxLength={500}
        onChange={(e) => setRemark(e.target.value)}
        placeholder={approving ? 'Remark (optional)' : 'Reason for rejection (required)'}
        aria-label="Remark"
        autoSize={{ minRows: 2, maxRows: 4 }}
      />
    </Modal>
  );
}

function ApprovalTable({ history }: { history: boolean }) {
  const canDecide = usePermission('approval.approve');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [documentType, setDocumentType] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [search, setSearch] = useState('');
  const [target, setTarget] = useState<{ approval: ApprovalRequest; decision: 'approve' | 'reject' } | null>(null);
  const list = useList<ApprovalRequest>(history ? APPROVALS.history : APPROVALS.pending, {
    page,
    page_size: pageSize,
    search,
    document_type: documentType,
    ...(history ? { status, from: range?.[0]?.format('YYYY-MM-DD'), to: range?.[1]?.format('YYYY-MM-DD') } : {}),
  });

  const columns: TableProps<ApprovalRequest>['columns'] = [
    { title: 'Type', dataIndex: 'document_label' },
    { title: 'Document', key: 'doc', render: (_, a) => <Link to={documentLink(a)}><strong>{a.document_number}</strong></Link> },
    { title: right('Amount'), dataIndex: 'amount', render: (v: string) => <MoneyText value={v} strong /> },
    { title: 'Requested by', dataIndex: 'requested_by_name' },
    { title: 'Requested', dataIndex: 'requested_at', render: (v: string) => <DateText value={v} withTime /> },
    { title: 'Approver', dataIndex: 'approver_role_name' },
    ...(history
      ? [
          { title: 'Status', dataIndex: 'status', render: (s: string) => <StatusTag status={s} /> },
          {
            title: 'Decided',
            key: 'decided',
            render: (_: unknown, a: ApprovalRequest) => (a.decided_by_name ? <>{a.decided_by_name}, <DateText value={a.decided_at} /></> : '—'),
          },
          { title: 'Remark', dataIndex: 'remark', render: (v: string) => v || '—' },
        ]
      : [
          {
            title: 'Actions',
            key: 'actions',
            render: (_: unknown, a: ApprovalRequest) =>
              canDecide && (
                <Tooltip title={a.can_decide ? undefined : 'Your own request, or not your role'}>
                  <Flex gap={4}>
                    <Button size="small" type="primary" icon={<CheckOutlined />} disabled={!a.can_decide} onClick={() => setTarget({ approval: a, decision: 'approve' })}>
                      Approve
                    </Button>
                    <Button size="small" danger icon={<CloseOutlined />} disabled={!a.can_decide} onClick={() => setTarget({ approval: a, decision: 'reject' })}>
                      Reject
                    </Button>
                  </Flex>
                </Tooltip>
              ),
          },
        ]),
  ];

  return (
    <>
      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        <Input.Search allowClear placeholder="Document number" style={{ width: 220 }} onSearch={(v) => { setSearch(v.trim()); setPage(1); }} />
        <Select allowClear placeholder="Document" options={DOCUMENT_TYPE_OPTIONS} style={{ width: 200 }} onChange={(v?: string) => { setDocumentType(v); setPage(1); }} />
        {history && (
          <>
            <Select
              allowClear
              placeholder="Status"
              style={{ width: 150 }}
              options={['pending', 'approved', 'rejected'].map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }))}
              onChange={(v?: string) => { setStatus(v); setPage(1); }}
            />
            <DatePicker.RangePicker allowEmpty={[true, true]} value={range} onChange={(v) => { setRange(v); setPage(1); }} />
          </>
        )}
      </Flex>
      <PagedTable<ApprovalRequest>
        query={list}
        columns={columns}
        page={page}
        pageSize={pageSize}
        onPageChange={(p, ps) => {
          setPage(p);
          setPageSize(ps);
        }}
        emptyText={history ? 'No approval requests yet' : 'Nothing is waiting for your approval'}
      />
      <DecisionModal target={target} onClose={() => setTarget(null)} />
    </>
  );
}

export default function ApprovalsPage() {
  return (
    <>
      <PageHeader title="Approvals" subtitle="Documents above an approval rule's amount wait here; nothing is posted until approved." />
      <Tabs
        items={[
          { key: 'pending', label: 'Pending', children: <ApprovalTable history={false} /> },
          { key: 'history', label: 'History', children: <ApprovalTable history /> },
        ]}
        destroyOnHidden
      />
    </>
  );
}
