import { useQuery } from '@tanstack/react-query';
import { Alert } from 'antd';

import { api } from '../api/client';
import type { PartyRecord } from '../api/parties';
import { compare, formatDecimal } from '../utils/decimal';

/** "Customer owes: 1,250.00" banner for the customer/supplier picked in a form. */
export default function PartyDue({ kind, id }: { kind: 'customers' | 'suppliers'; id?: number }) {
  const party = useQuery({
    queryKey: [`/${kind}`, 'detail', id],
    queryFn: () => api.get<PartyRecord>(`/${kind}/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  if (!id || !party.data) return null;
  const due = party.data.due;
  const label = kind === 'customers' ? 'Customer owes' : 'We owe';
  return (
    <Alert
      type={compare(due, 0) > 0 ? 'warning' : 'success'}
      showIcon
      style={{ marginBottom: 16 }}
      title={
        compare(due, 0) >= 0 ? (
          <>{label}: <strong>{formatDecimal(due, 2)}</strong></>
        ) : (
          <>Advance: <strong>{formatDecimal(due.replace('-', ''), 2)}</strong> (no due)</>
        )
      }
    />
  );
}
