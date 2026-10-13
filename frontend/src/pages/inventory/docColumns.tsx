import { Typography } from 'antd';
import { Link } from 'react-router';

import type { DocStatus } from '../../api/inventory';
import DateText from '../../components/DateText';
import StatusTag from '../../components/StatusTag';

/** Columns shared by every stock document list. */
export function numberColumn(basePath: string) {
  return {
    title: 'Number',
    key: 'number',
    width: 130,
    render: (_: unknown, d: { id: number; number: string }) => (
      <Link to={`${basePath}/${d.id}`}>
        <Typography.Text strong>{d.number}</Typography.Text>
      </Link>
    ),
  };
}

export function dateColumn(field: string) {
  return { title: 'Date', dataIndex: field, width: 120, render: (v: string) => <DateText value={v} /> };
}

export const tailColumns = [
  { title: 'Lines', key: 'lines', width: 70, align: 'right' as const, render: (_: unknown, d: { items: unknown[] }) => d.items.length },
  { title: 'Status', dataIndex: 'status', width: 120, render: (s: DocStatus) => <StatusTag status={s} /> },
  { title: 'Created by', dataIndex: 'created_by_name' },
];
