import { CheckOutlined, CloseOutlined, DollarOutlined, SaveOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Empty,
  Flex,
  Form,
  InputNumber,
  Modal,
  Radio,
  Select,
  Skeleton,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { useEffect, useMemo, useState } from 'react';

import { errorMessage } from '../../api/client';
import { ATTENDANCE_STATUSES, EMPLOYEES, employeesApi } from '../../api/employees';
import type { AttendanceRow, AttendanceStatus, PayrollItem, PayrollRun } from '../../api/employees';
import { useLookups } from '../../api/master';
import { MONEY, useAccountBalance } from '../../api/money';
import ConfirmButton from '../../components/ConfirmButton';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import MoneyText from '../../components/MoneyText';
import PageHeader from '../../components/PageHeader';
import StatusTag from '../../components/StatusTag';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { compare, formatDecimal, subtract, sum } from '../../utils/decimal';

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;
const STATUS_LABELS: Record<AttendanceStatus, string> = { present: 'Present', absent: 'Absent', leave: 'Leave', late: 'Late' };

// --- Attendance -----------------------------------------------------------------------------

function AttendanceTab() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const canMark = usePermission('attendance.edit');
  const [day, setDay] = useState<Dayjs>(dayjs());
  const date = day.format('YYYY-MM-DD');
  const sheet = useQuery({ queryKey: [EMPLOYEES.attendance, date], queryFn: () => employeesApi.sheet(date) });
  const [edits, setEdits] = useState<Record<number, AttendanceStatus>>({});
  useEffect(() => setEdits({}), [date]);

  const rows = (sheet.data?.rows ?? []).map((r) => ({ ...r, status: edits[r.employee_id] ?? r.status }));
  const unsaved = rows.filter((r) => !r.saved || edits[r.employee_id] !== undefined).length;
  const counts = Object.fromEntries(ATTENDANCE_STATUSES.map((s) => [s, rows.filter((r) => r.status === s).length]));

  const save = useMutation({
    mutationFn: () => employeesApi.mark(date, rows.map((r) => ({ employee_id: r.employee_id, status: r.status }))),
    meta: { silent: true },
    onSuccess: (result) => {
      queryClient.setQueryData([EMPLOYEES.attendance, date], result);
      setEdits({});
      message.success(`Attendance saved for ${day.format('DD MMM YYYY')}`);
    },
  });

  const columns: TableProps<AttendanceRow>['columns'] = [
    { title: 'Code', dataIndex: 'employee_code', render: (v: string) => <strong>{v}</strong> },
    { title: 'Employee', dataIndex: 'employee_name' },
    { title: 'Designation', dataIndex: 'designation', render: (v: string) => v || '—' },
    {
      title: 'Status',
      key: 'status',
      render: (_, r) => (
        <Radio.Group
          size="small"
          optionType="button"
          buttonStyle="solid"
          disabled={!canMark}
          value={r.status}
          onChange={(e) => setEdits((prev) => ({ ...prev, [r.employee_id]: e.target.value }))}
          options={ATTENDANCE_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] }))}
          aria-label={`Attendance ${r.employee_code}`}
        />
      ),
    },
    {
      title: '',
      key: 'saved',
      render: (_, r) =>
        !r.saved ? <Tag>Not saved</Tag> : edits[r.employee_id] !== undefined ? <Tag color="gold">Changed</Tag> : <Tag color="green">Saved</Tag>,
    },
  ];

  return (
    <>
      <Flex gap={12} wrap align="center" style={{ marginBottom: 16 }}>
        <DatePicker
          allowClear={false}
          value={day}
          onChange={(v) => v && setDay(v)}
          disabledDate={(d) => d.isAfter(dayjs(), 'day')}
          aria-label="Attendance date"
        />
        {ATTENDANCE_STATUSES.map((s) => (
          <Tag key={s} color={s === 'absent' ? 'red' : s === 'present' ? 'green' : s === 'leave' ? 'blue' : 'gold'}>
            {STATUS_LABELS[s]}: {counts[s] ?? 0}
          </Tag>
        ))}
        {canMark && (
          <Flex gap={8} style={{ marginLeft: 'auto' }}>
            <Button onClick={() => setEdits(Object.fromEntries(rows.map((r) => [r.employee_id, 'present' as const])))} disabled={!rows.length}>
              All present
            </Button>
            <Button type="primary" icon={<SaveOutlined />} loading={save.isPending} disabled={!rows.length || !unsaved} onClick={() => save.mutate()}>
              Save attendance{unsaved ? ` (${unsaved})` : ''}
            </Button>
          </Flex>
        )}
      </Flex>
      {save.isError && <Alert type="error" showIcon title="Could not save attendance" description={errorMessage(save.error)} style={{ marginBottom: 12 }} />}
      {sheet.isError ? (
        <ErrorState error={sheet.error} onRetry={() => sheet.refetch()} />
      ) : (
        <Table<AttendanceRow>
          rowKey="employee_id"
          size="middle"
          loading={sheet.isFetching}
          columns={columns}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: 'No active employees' }}
        />
      )}
      <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
        Employees not marked yet start as present. Only "Absent" days reduce pay (base salary / 30 per day); leave and late don't.
      </Typography.Paragraph>
    </>
  );
}

// --- Payroll --------------------------------------------------------------------------------

function PayModal({ run, open, onClose }: { run: PayrollRun; open: boolean; onClose: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const lookups = useLookups();
  const canSeeBalance = usePermission('money_account.view');
  const [form] = Form.useForm<{ account_id: number; payment_date: Dayjs }>();
  const accountId = Form.useWatch('account_id', form);
  const balance = useAccountBalance(accountId, canSeeBalance && open);
  const mutation = useMutation({
    mutationFn: (v: { account_id: number; payment_date: Dayjs }) =>
      employeesApi.pay(run.id, { account_id: v.account_id, payment_date: v.payment_date.format('YYYY-MM-DD') }),
    meta: { silent: true },
    onSuccess: async (paid) => {
      message.success(`${paid.prl_number} paid: ${formatDecimal(paid.total_net, 2)} from ${paid.account_name}`);
      onClose();
      await Promise.all([EMPLOYEES.payroll, MONEY.accounts].map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
    },
    onError: (error) => applyServerErrors(form, error, { INSUFFICIENT_FUNDS: 'account_id', INACTIVE_ACCOUNT: 'account_id' }),
  });
  return (
    <Modal
      title={`Pay ${run.prl_number} (${dayjs(`${run.month}-01`).format('MMMM YYYY')})`}
      open={open}
      onCancel={onClose}
      okText={`Pay ${formatDecimal(run.total_net, 2)}`}
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      forceRender
      afterOpenChange={(visible) => {
        if (visible) {
          form.resetFields();
          mutation.reset();
        }
      }}
    >
      {mutation.isError && <Alert type="error" showIcon title="Could not pay" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />}
      <Typography.Paragraph type="secondary">
        One payment of the total net pay leaves the chosen account (recorded as Salary expense). The run can't be changed afterwards.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" initialValues={{ payment_date: dayjs() }} onFinish={(v) => mutation.mutate(v)}>
        <Form.Item
          name="account_id"
          label="Pay from"
          rules={[{ required: true, message: 'Choose the account' }]}
          extra={canSeeBalance && balance.data ? `Balance: ${formatDecimal(balance.data.balance, 2)}` : undefined}
        >
          <Select options={(lookups.data?.money_accounts ?? []).map((a) => ({ label: a.name, value: a.id }))} />
        </Form.Item>
        <Form.Item name="payment_date" label="Payment date" rules={[{ required: true }]}>
          <DatePicker allowClear={false} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

type Adjust = Record<number, { bonus: string; other_deduction: string }>;

function RunView({ run }: { run: PayrollRun }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const canEdit = usePermission('payroll.edit');
  const canCancel = usePermission('payroll.delete');
  const draft = run.status === 'draft';
  const [adjust, setAdjust] = useState<Adjust>({});
  const [paying, setPaying] = useState(false);
  useEffect(() => setAdjust({}), [run.id, run.total_net]);

  const line = (i: PayrollItem) => {
    const a = adjust[i.id];
    const bonus = a?.bonus ?? i.bonus;
    const other = a?.other_deduction ?? i.other_deduction;
    const net = sum([subtract(subtract(i.base_salary, i.absence_deduction, 2), other || '0', 2), bonus || '0'], 2);
    return { bonus, other, net };
  };
  const dirty = Object.keys(adjust).length > 0;
  const total = sum(run.items.map((i) => line(i).net), 2);
  const negative = run.items.some((i) => compare(line(i).net, 0) < 0);

  const refresh = () => Promise.all([EMPLOYEES.payroll].map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
  const save = useMutation({
    mutationFn: () =>
      employeesApi.updateRun(
        run.id,
        Object.entries(adjust).map(([id, a]) => ({ id: Number(id), bonus: a.bonus || '0', other_deduction: a.other_deduction || '0' })),
      ),
    meta: { silent: true },
    onSuccess: async () => {
      message.success('Payroll updated');
      await refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: () => employeesApi.cancel(run.id),
    meta: { silent: true },
    onSuccess: async () => {
      message.success(`${run.prl_number} cancelled`);
      await refresh();
    },
  });
  const failed = [save, cancel].find((m) => m.isError);

  const edit = (i: PayrollItem, field: 'bonus' | 'other_deduction', value: string | null) =>
    setAdjust((prev) => {
      const current = prev[i.id] ?? { bonus: i.bonus, other_deduction: i.other_deduction };
      return { ...prev, [i.id]: { ...current, [field]: value ?? '0' } };
    });
  const amountInput = (i: PayrollItem, field: 'bonus' | 'other_deduction', value: string, label: string) =>
    draft && canEdit ? (
      <InputNumber<string> stringMode size="small" min="0" precision={2} value={value} onChange={(v) => edit(i, field, v)} style={{ width: 120 }} aria-label={`${label} ${i.employee_code}`} />
    ) : (
      <MoneyText value={value} />
    );

  const columns: TableProps<PayrollItem>['columns'] = [
    { title: 'Employee', key: 'e', render: (_, i) => <><strong>{i.employee_code}</strong> {i.employee_name}</> },
    { title: 'Designation', dataIndex: 'designation', render: (v: string) => v || '—' },
    { title: right('Base salary'), dataIndex: 'base_salary', render: (v: string) => <MoneyText value={v} /> },
    { title: right('Absent days'), dataIndex: 'absent_days', render: (v: number) => <span style={{ display: 'block', textAlign: 'right' }}>{v}</span> },
    { title: right('Absence deduction'), dataIndex: 'absence_deduction', render: (v: string) => <MoneyText value={compare(v, 0) > 0 ? `-${v}` : v} /> },
    { title: 'Bonus', key: 'bonus', render: (_, i) => amountInput(i, 'bonus', line(i).bonus, 'Bonus') },
    { title: 'Other deduction', key: 'other', render: (_, i) => amountInput(i, 'other_deduction', line(i).other, 'Other deduction') },
    {
      title: right('Net pay'),
      key: 'net',
      render: (_, i) => {
        const net = line(i).net;
        return compare(net, 0) < 0 ? <Typography.Text type="danger" style={{ display: 'block', textAlign: 'right' }}>{formatDecimal(net, 2)}</Typography.Text> : <MoneyText value={net} strong />;
      },
    },
  ];

  return (
    <Card
      size="small"
      title={
        <Flex gap={8} align="center" wrap>
          <strong>{run.prl_number}</strong>
          <StatusTag status={run.status} />
          <Typography.Text type="secondary">{run.employee_count} employees · generated by {run.created_by_name}</Typography.Text>
        </Flex>
      }
      extra={
        draft && (
          <Flex gap={8} wrap>
            {canCancel && (
              <ConfirmButton size="small" icon={<CloseOutlined />} danger confirm={`Cancel ${run.prl_number}?`} description="You can generate the month again afterwards." okText="Cancel run" loading={cancel.isPending} onConfirm={() => cancel.mutateAsync()}>
                Cancel
              </ConfirmButton>
            )}
            {canEdit && (
              <Button size="small" icon={<CheckOutlined />} disabled={!dirty || negative} loading={save.isPending} onClick={() => save.mutate()}>
                Save changes
              </Button>
            )}
            {canEdit && (
              <Button size="small" type="primary" icon={<DollarOutlined />} disabled={dirty || compare(run.total_net, 0) <= 0} onClick={() => setPaying(true)}>
                Pay
              </Button>
            )}
          </Flex>
        )
      }
    >
      {failed && <Alert type="error" showIcon closable={{ onClose: () => failed.reset() }} title="Action failed" description={errorMessage(failed.error)} style={{ marginBottom: 12 }} />}
      {dirty && <Alert type="info" showIcon title="Save your changes before paying." style={{ marginBottom: 12 }} />}
      {run.status === 'paid' && (
        <Descriptions
          size="small"
          style={{ marginBottom: 12 }}
          items={[
            { label: 'Paid from', children: run.account_name },
            { label: 'Payment date', children: <DateText value={run.payment_date} /> },
            { label: 'Paid by', children: run.paid_by_name },
          ]}
        />
      )}
      <Table<PayrollItem>
        rowKey="id"
        size="small"
        pagination={false}
        columns={columns}
        dataSource={run.items}
        scroll={{ x: 'max-content' }}
        summary={() => (
          <Table.Summary.Row>
            <Table.Summary.Cell index={0} colSpan={7} align="right">
              <strong>Total net pay</strong>
            </Table.Summary.Cell>
            <Table.Summary.Cell index={1}>
              <MoneyText value={total} strong />
            </Table.Summary.Cell>
          </Table.Summary.Row>
        )}
      />
      <PayModal run={run} open={paying} onClose={() => setPaying(false)} />
    </Card>
  );
}

function PayrollTab() {
  const queryClient = useQueryClient();
  const canGenerate = usePermission('payroll.create');
  const [month, setMonth] = useState<Dayjs>(dayjs().subtract(1, 'month'));
  const key = month.format('YYYY-MM');
  const runs = useList<PayrollRun>(EMPLOYEES.payroll, { month: key, page_size: 20 });
  const recent = useList<PayrollRun>(EMPLOYEES.payroll, { page_size: 6 });
  const generate = useMutation({
    mutationFn: () => employeesApi.generate(key),
    meta: { silent: true },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [EMPLOYEES.payroll] }),
  });
  const live = useMemo(() => (runs.data?.items ?? []).find((r) => r.status !== 'cancelled'), [runs.data]);
  const cancelledCount = (runs.data?.items ?? []).filter((r) => r.status === 'cancelled').length;

  return (
    <>
      <Flex gap={12} wrap align="center" style={{ marginBottom: 16 }}>
        <DatePicker picker="month" allowClear={false} value={month} onChange={(v) => v && setMonth(v)} aria-label="Payroll month" />
        {!live && canGenerate && runs.data && (
          <Button type="primary" icon={<ThunderboltOutlined />} loading={generate.isPending} onClick={() => generate.mutate()}>
            Generate payroll for {month.format('MMMM YYYY')}
          </Button>
        )}
        {cancelledCount > 0 && <Typography.Text type="secondary">{cancelledCount} cancelled run(s) this month</Typography.Text>}
      </Flex>
      {generate.isError && <Alert type="error" showIcon title="Could not generate" description={errorMessage(generate.error)} style={{ marginBottom: 12 }} />}
      {runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
      ) : !runs.data ? (
        <Skeleton active />
      ) : live ? (
        <RunView run={live} />
      ) : (
        <Empty description={`No payroll for ${month.format('MMMM YYYY')} yet`} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
      <Typography.Title level={5} style={{ marginTop: 24 }}>
        Recent runs
      </Typography.Title>
      <Table<PayrollRun>
        rowKey="id"
        size="small"
        pagination={false}
        loading={recent.isFetching}
        dataSource={recent.data?.items ?? []}
        onRow={(r) => ({ onClick: () => setMonth(dayjs(`${r.month}-01`)), style: { cursor: 'pointer' } })}
        columns={[
          { title: 'Run', dataIndex: 'prl_number', render: (v: string) => <strong>{v}</strong> },
          { title: 'Month', dataIndex: 'month', render: (v: string) => dayjs(`${v}-01`).format('MMM YYYY') },
          { title: right('Total net'), dataIndex: 'total_net', render: (v: string) => <MoneyText value={v} /> },
          { title: 'Status', dataIndex: 'status', render: (s: string) => <StatusTag status={s} /> },
          { title: 'Paid from', dataIndex: 'account_name', render: (v: string | null) => v ?? '—' },
        ]}
        locale={{ emptyText: 'No payroll runs yet' }}
      />
    </>
  );
}

export default function AttendancePayrollPage() {
  const canAttendance = usePermission('attendance.view');
  const canPayroll = usePermission('payroll.view');
  return (
    <>
      <PageHeader title="Attendance & Payroll" />
      <Tabs
        destroyOnHidden
        items={[
          ...(canAttendance ? [{ key: 'attendance', label: 'Attendance', children: <AttendanceTab /> }] : []),
          ...(canPayroll ? [{ key: 'payroll', label: 'Payroll', children: <PayrollTab /> }] : []),
        ]}
      />
    </>
  );
}
