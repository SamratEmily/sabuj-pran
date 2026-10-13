import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Flex,
  Form,
  Input,
  Menu,
  Modal,
  Row,
  Skeleton,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { TableProps } from 'antd';
import { useMemo, useState } from 'react';

import { ADMIN, adminApi } from '../../api/admin';
import type { PermissionGroup, RoleRecord } from '../../api/admin';
import ConfirmButton from '../../components/ConfirmButton';
import ErrorState from '../../components/ErrorState';
import PageHeader from '../../components/PageHeader';
import { useList, useSave } from '../../hooks/useApi';
import { ME_QUERY_KEY, useAuth } from '../../hooks/useAuth';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { notifyError } from '../../utils/notify';

const ADMIN_ROLE = 'Admin';
const CRUD = ['view', 'create', 'edit', 'delete'] as const;

const MODULE_LABELS: Record<string, string> = {
  admin: 'Administration',
  approvals: 'Approvals',
  master: 'Master Data',
  parties: 'Customers & Suppliers',
  sales: 'Sales',
  purchase: 'Purchase',
  inventory: 'Inventory',
  money: 'Money',
  employees: 'Employees',
  dashboard: 'Dashboard',
};

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

interface ResourceRow {
  resource: string;
  crud: Partial<Record<(typeof CRUD)[number], string>>;
  other: { code: string; label: string }[];
}

/** Group a module's codes by resource: CRUD actions as columns, anything else under "Other". */
function toRows(group: PermissionGroup): ResourceRow[] {
  const rows = new Map<string, ResourceRow>();
  for (const { code } of group.permissions) {
    const [resource, action] = code.split('.');
    const row = rows.get(resource) ?? { resource, crud: {}, other: [] };
    if ((CRUD as readonly string[]).includes(action)) row.crud[action as (typeof CRUD)[number]] = code;
    else row.other.push({ code, label: humanize(action) });
    rows.set(resource, row);
  }
  return [...rows.values()];
}

// ---------------------------------------------------------------------------------------

function PermissionMatrix({
  role,
  groups,
  initial,
  editable,
}: {
  role: RoleRecord;
  groups: PermissionGroup[];
  initial: string[];
  editable: boolean;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [checked, setChecked] = useState<Set<string>>(() => new Set(initial));
  const isAdminRole = role.name === ADMIN_ROLE;
  const readOnly = !editable || isAdminRole;

  const dirty = checked.size !== initial.length || initial.some((c) => !checked.has(c));
  const total = groups.reduce((n, g) => n + g.permissions.length, 0);

  const save = useMutation({
    mutationFn: () => adminApi.setRolePermissions(role.id, [...checked]),
    onSuccess: async () => {
      message.success(`Permissions saved for ${role.name}`);
      await queryClient.invalidateQueries({ queryKey: [ADMIN.roles] });
      // Editing your own role changes your menu right away.
      if (user?.role === role.name) await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });

  const toggle = (codes: string[], on: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      codes.forEach((c) => (on ? next.add(c) : next.delete(c)));
      return next;
    });

  const box = (code: string | undefined) =>
    code ? (
      <Checkbox
        checked={checked.has(code)}
        disabled={readOnly}
        onChange={(e) => toggle([code], e.target.checked)}
        aria-label={code}
      />
    ) : null;

  const columns: TableProps<ResourceRow>['columns'] = [
    { title: 'Resource', dataIndex: 'resource', render: (r: string) => humanize(r) },
    ...CRUD.map((action) => ({
      title: humanize(action),
      key: action,
      width: 80,
      align: 'center' as const,
      render: (_: unknown, row: ResourceRow) => box(row.crud[action]),
    })),
    {
      title: 'Other',
      key: 'other',
      render: (_, row) => (
        <Flex gap={12} wrap>
          {row.other.map((o) => (
            <Checkbox
              key={o.code}
              checked={checked.has(o.code)}
              disabled={readOnly}
              onChange={(e) => toggle([o.code], e.target.checked)}
            >
              {o.label}
            </Checkbox>
          ))}
        </Flex>
      ),
    },
  ];

  return (
    <>
      <Flex justify="space-between" align="center" gap={8} wrap style={{ marginBottom: 12 }}>
        <Typography.Text type="secondary">
          {checked.size} of {total} permissions
        </Typography.Text>
        {!readOnly && (
          <Flex gap={8}>
            <Button disabled={!dirty || save.isPending} onClick={() => setChecked(new Set(initial))}>
              Undo changes
            </Button>
            <Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
              Save permissions
            </Button>
          </Flex>
        )}
      </Flex>
      {isAdminRole && (
        <Alert type="info" showIcon title="The Admin role always has every permission." style={{ marginBottom: 12 }} />
      )}
      {!editable && !isAdminRole && (
        <Alert type="info" showIcon title="You can view but not change permissions." style={{ marginBottom: 12 }} />
      )}
      <Flex vertical gap={12}>
        {groups.map((group) => {
          const codes = group.permissions.map((p) => p.code);
          const on = codes.filter((c) => checked.has(c)).length;
          return (
            <Card
              key={group.module}
              size="small"
              title={
                <Checkbox
                  checked={on === codes.length}
                  indeterminate={on > 0 && on < codes.length}
                  disabled={readOnly}
                  onChange={(e) => toggle(codes, e.target.checked)}
                >
                  <strong>{MODULE_LABELS[group.module] ?? humanize(group.module)}</strong>
                </Checkbox>
              }
              extra={<Typography.Text type="secondary">{on}/{codes.length}</Typography.Text>}
              styles={{ body: { padding: 0 } }}
            >
              <Table<ResourceRow>
                rowKey="resource"
                size="small"
                pagination={false}
                columns={columns}
                dataSource={toRows(group)}
                scroll={{ x: 'max-content' }}
              />
            </Card>
          );
        })}
      </Flex>
    </>
  );
}

// ---------------------------------------------------------------------------------------

function RoleFormModal({ role, open, onClose, onSaved }: {
  role: RoleRecord | null;
  open: boolean;
  onClose: () => void;
  onSaved: (role: RoleRecord) => void;
}) {
  const [form] = Form.useForm<{ name: string; description: string }>();
  const save = useSave<{ name: string; description: string }, RoleRecord>(ADMIN.roles, { silent: true });
  const submit = async (values: { name: string; description: string }) => {
    try {
      onSaved(await save.mutateAsync({ id: role?.id, data: values }));
      onClose();
    } catch (error) {
      if (!applyServerErrors(form, error, { ROLE_NAME_TAKEN: 'name', SYSTEM_ROLE: 'name' })) {
        notifyError(error, 'Could not save role');
      }
    }
  };
  return (
    <Modal
      title={role ? 'Edit role' : 'New role'}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={save.isPending}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={{ name: role?.name ?? '', description: role?.description ?? '' }}
        onFinish={submit}
      >
        <Form.Item
          name="name"
          label="Name"
          rules={[{ required: true, whitespace: true, message: 'Enter a name' }, { max: 100 }]}
          extra={role?.is_system ? 'System roles cannot be renamed.' : undefined}
        >
          <Input disabled={role?.is_system} />
        </Form.Item>
        <Form.Item name="description" label="Description" rules={[{ max: 255 }]}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------------------

export default function RolesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const canCreate = usePermission('role.create');
  const canEdit = usePermission('role.edit');
  const canDelete = usePermission('role.delete');

  const roles = useList<RoleRecord>(ADMIN.roles, { page_size: 100 });
  const groups = useQuery({ queryKey: [ADMIN.permissions], queryFn: adminApi.permissionGroups, staleTime: Infinity });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [modal, setModal] = useState<{ role: RoleRecord | null } | null>(null);

  const roleList = useMemo(() => roles.data?.items ?? [], [roles.data]);
  const selected = roleList.find((r) => r.id === selectedId) ?? roleList[0] ?? null;

  const rolePerms = useQuery({
    queryKey: [ADMIN.roles, 'permissions', selected?.id],
    queryFn: () => adminApi.rolePermissions(selected!.id),
    enabled: selected !== null,
  });

  const remove = useMutation({
    mutationFn: (id: number) => adminApi.deleteRole(id),
    onSuccess: async () => {
      message.success('Role deleted');
      setSelectedId(null);
      await queryClient.invalidateQueries({ queryKey: [ADMIN.roles] });
    },
  });

  return (
    <>
      <PageHeader
        title="Roles & Permissions"
        actions={
          canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModal({ role: null })}>
              New role
            </Button>
          )
        }
      />
      {roles.isError && <ErrorState error={roles.error} onRetry={() => roles.refetch()} />}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={7}>
          <Card size="small" title="Roles" styles={{ body: { padding: 4 } }}>
            {roles.isPending ? (
              <Skeleton active style={{ padding: 12 }} />
            ) : roleList.length === 0 ? (
              <Empty description="No roles" />
            ) : (
              <Menu
                mode="inline"
                style={{ borderInlineEnd: 0 }}
                selectedKeys={selected ? [String(selected.id)] : []}
                onClick={({ key }) => setSelectedId(Number(key))}
                items={roleList.map((r) => ({
                  key: String(r.id),
                  label: (
                    <Flex justify="space-between" align="center">
                      <span>{r.name}</span>
                      <Tooltip title={`${r.user_count} user(s)`}>
                        <Badge count={r.user_count} showZero color="#8c8c8c" />
                      </Tooltip>
                    </Flex>
                  ),
                }))}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={17}>
          {selected && (
            <Card
              title={
                <Flex align="center" gap={8}>
                  {selected.name}
                  {selected.is_system && <Tag>System</Tag>}
                </Flex>
              }
              extra={
                <Flex gap={4}>
                  {canEdit && (
                    <Button size="small" icon={<EditOutlined />} onClick={() => setModal({ role: selected })}>
                      Edit
                    </Button>
                  )}
                  {canDelete && (
                    <Tooltip
                      title={
                        selected.is_system
                          ? 'System roles cannot be deleted'
                          : selected.user_count > 0
                            ? 'Reassign its users first'
                            : undefined
                      }
                    >
                      <span>
                        <ConfirmButton
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          disabled={selected.is_system || selected.user_count > 0}
                          confirm={`Delete role "${selected.name}"?`}
                          onConfirm={() => remove.mutateAsync(selected.id)}
                        >
                          Delete
                        </ConfirmButton>
                      </span>
                    </Tooltip>
                  )}
                </Flex>
              }
            >
              {selected.description && (
                <Typography.Paragraph type="secondary">{selected.description}</Typography.Paragraph>
              )}
              {groups.isError || rolePerms.isError ? (
                <ErrorState
                  error={groups.error ?? rolePerms.error}
                  onRetry={() => {
                    void groups.refetch();
                    void rolePerms.refetch();
                  }}
                />
              ) : groups.isPending || rolePerms.isPending ? (
                <Skeleton active />
              ) : (
                <PermissionMatrix
                  // Remount (reset local checkboxes) when the role or its saved permissions change.
                  key={`${selected.id}-${rolePerms.dataUpdatedAt}`}
                  role={selected}
                  groups={groups.data}
                  initial={rolePerms.data.codes}
                  editable={canEdit}
                />
              )}
            </Card>
          )}
        </Col>
      </Row>
      <RoleFormModal
        open={modal !== null}
        role={modal?.role ?? null}
        onClose={() => setModal(null)}
        onSaved={(r) => {
          message.success(modal?.role ? 'Role updated' : 'Role created');
          setSelectedId(r.id);
        }}
      />
    </>
  );
}
