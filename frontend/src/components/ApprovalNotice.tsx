import { useQuery } from '@tanstack/react-query';
import { Alert } from 'antd';
import { Link } from 'react-router';

import { APPROVALS, approvalsApi } from '../api/approvals';
import type { DocumentType } from '../api/approvals';
import { usePermission } from '../hooks/usePermission';

interface Props {
  documentType: DocumentType;
  number: string;
  status: string;
}

/** Banner on a document that is waiting for approval or was rejected. Users who can see
 *  approvals also get the approver role / remark. */
export default function ApprovalNotice({ documentType, number, status }: Props) {
  const canView = usePermission('approval.view');
  const relevant = status === 'pending_approval' || status === 'rejected';
  const latest = useQuery({
    queryKey: [APPROVALS.history, 'latest', documentType, number],
    queryFn: () => approvalsApi.latestFor(documentType, number),
    enabled: relevant && canView,
  });
  if (!relevant) return null;
  const a = latest.data;
  if (status === 'pending_approval') {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        title={`Waiting for approval${a ? ` by ${a.approver_role_name}` : ''}. Nothing is posted until it is approved.`}
        description={a && canView ? <Link to="/admin/approvals">Open pending approvals</Link> : undefined}
      />
    );
  }
  return (
    <Alert
      type="error"
      showIcon
      style={{ marginBottom: 16 }}
      title={`Rejected${a?.decided_by_name ? ` by ${a.decided_by_name}` : ''}. Nothing was posted.`}
      description={a?.remark ? `Reason: ${a.remark}` : undefined}
    />
  );
}
