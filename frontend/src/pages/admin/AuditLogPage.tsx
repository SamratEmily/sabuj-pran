import { useQuery } from '@tanstack/react-query';
import { DatePicker, Flex, Input, Select, Table, Tag, Typography, theme } from 'antd';
import type { TableProps } from 'antd';
import type { Dayjs } from 'dayjs';
import { useState } from 'react';

import { ADMIN, adminApi } from '../../api/admin';
import type { AdminUser, AuditLogRecord } from '../../api/admin';
import DateText from '../../components/DateText';
import PageHeader from '../../components/PageHeader';
import PagedTable from '../../components/PagedTable';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';

const ACTION_COLORS: Record<string, string> = {
  create: 'green',
  update: 'blue',
  delete: 'red',
  deactivate: 'orange',
  activate: 'cyan',
  approve: 'green',
  reject: 'red',
  cancel: 'volcano',
  post: 'purple',
  login: 'default',
  logout: 'default',
};

function display(value: unknown): string {
  if (value === undefined) return '';
  if (value === null) return '—';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** Field-by-field old vs new; changed fields highlighted. */
function ValuesDiff({ log }: { log: AuditLogRecord }) {
  const { token } = theme.useToken();
  const oldValues = log.old_values ?? {};
  const newValues = log.new_values ?? {};
  const keys = [...new Set([...Object.keys(oldValues), ...Object.keys(newValues)])];
  const rows = keys.map((key) => ({
    key,
    old: display(oldValues[key]),
    new: display(newValues[key]),
    changed: display(oldValues[key]) !== display(newValues[key]),
  }));
  return (
    <Table
      size="small"
      pagination={false}
      rowKey="key"
      dataSource={rows}
      onRow={(r) => ({ style: r.changed && log.old_values && log.new_values ? { background: token.colorWarningBg } : undefined })}
      columns={[
        { title: 'Field', dataIndex: 'key', width: 200, render: (k: string) => <Typography.Text code>{k}</Typography.Text> },
        ...(log.old_values ? [{ title: 'Before', dataIndex: 'old', render: (v: string) => <Typography.Text type="secondary" style={{ wordBreak: 'break-all' }}>{v}</Typography.Text> }] : []),
        ...(log.new_values ? [{ title: 'After', dataIndex: 'new', render: (v: string) => <span style={{ wordBreak: 'break-all' }}>{v}</span> }] : []),
      ]}
    />
  );
}

export default function AuditLogPage() {
  const canListUsers = usePermission('user.view');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [filters, setFilters] = useState<{ user_id?: number; entity_type?: string; action?: string; search?: string }>({});

  const logs = useList<AuditLogRecord>(ADMIN.auditLogs, {
    page,
    page_size: pageSize,
    date_from: range?.[0]?.format('YYYY-MM-DD'),
    date_to: range?.[1]?.format('YYYY-MM-DD'),
    ...filters,
  });
  const facets = useQuery({ queryKey: [ADMIN.auditLogs, 'facets'], queryFn: adminApi.auditFacets });
  const users = useList<AdminUser>(ADMIN.users, { page_size: 100 }, canListUsers);

  const setFilter = (patch: typeof filters) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };

  const columns: TableProps<AuditLogRecord>['columns'] = [
    { title: 'When', dataIndex: 'created_at', width: 190, render: (v: string) => <DateText value={v} withTime /> },
    { title: 'User', dataIndex: 'user_name', render: (v: string | null) => v ?? <Typography.Text type="secondary">System</Typography.Text> },
    { title: 'Action', dataIndex: 'action', render: (a: string) => <Tag color={ACTION_COLORS[a] ?? 'default'}>{a.replace(/_/g, ' ')}</Tag> },
    {
      title: 'Entity',
      key: 'entity',
      render: (_, l) => (
        <>
          {l.entity_type.replace(/_/g, ' ')}
          {l.entity_id && <Typography.Text type="secondary"> #{l.entity_id}</Typography.Text>}
        </>
      ),
    },
    { title: 'Summary', dataIndex: 'summary' },
    { title: 'IP', dataIndex: 'ip_address', render: (v: string | null) => v ?? '—' },
  ];

  return (
    <>
      <PageHeader title="Audit Log" subtitle="Every login, change, posting and approval. Read-only." />
      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        <DatePicker.RangePicker
          allowEmpty={[true, true]}
          value={range}
          onChange={(v) => {
            setRange(v);
            setPage(1);
          }}
        />
        {canListUsers && (
          <Select
            allowClear
            showSearch={{ optionFilterProp: 'label' }}
            placeholder="User"
            style={{ width: 200 }}
            loading={users.isPending}
            options={(users.data?.items ?? []).map((u) => ({ label: u.full_name, value: u.id }))}
            onChange={(user_id?: number) => setFilter({ user_id })}
          />
        )}
        <Select
          allowClear
          placeholder="Entity"
          style={{ width: 180 }}
          options={(facets.data?.entity_types ?? []).map((e) => ({ label: e.replace(/_/g, ' '), value: e }))}
          onChange={(entity_type?: string) => setFilter({ entity_type })}
        />
        <Select
          allowClear
          placeholder="Action"
          style={{ width: 160 }}
          options={(facets.data?.actions ?? []).map((a) => ({ label: a.replace(/_/g, ' '), value: a }))}
          onChange={(action?: string) => setFilter({ action })}
        />
        <Input.Search
          allowClear
          placeholder="Search summary"
          style={{ width: 240 }}
          onSearch={(v) => setFilter({ search: v.trim() || undefined })}
        />
      </Flex>

      <PagedTable<AuditLogRecord>
        query={logs}
        columns={columns}
        page={page}
        pageSize={pageSize}
        onPageChange={(p, ps) => {
          setPage(p);
          setPageSize(ps);
        }}
        emptyText="No audit entries match these filters"
        totalLabel="entries"
        expandable={{
          rowExpandable: (l) => l.old_values !== null || l.new_values !== null,
          expandedRowRender: (l) => <ValuesDiff log={l} />,
        }}
      />
    </>
  );
}
