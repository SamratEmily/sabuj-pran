import { Tag } from 'antd';

// One colour map for every document/record status in the app.
const STATUS_COLORS: Record<string, string> = {
  draft: 'default',
  sent: 'blue',
  accepted: 'green',
  rejected: 'red',
  converted: 'purple',
  confirmed: 'blue',
  pending_approval: 'gold',
  pending: 'gold',
  approved: 'green',
  partially_delivered: 'orange',
  delivered: 'green',
  partially_received: 'orange',
  received: 'green',
  posted: 'green',
  cancelled: 'default',
  unpaid: 'red',
  partial: 'orange',
  paid: 'green',
  active: 'green',
  inactive: 'default',
};

export function statusLabel(status: string): string {
  const text = status.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

interface Props {
  status: string | null | undefined;
}

export default function StatusTag({ status }: Props) {
  if (!status) return null;
  return <Tag color={STATUS_COLORS[status] ?? 'default'}>{statusLabel(status)}</Tag>;
}
