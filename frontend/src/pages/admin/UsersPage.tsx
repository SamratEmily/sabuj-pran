import { KeyOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { App, Button, Checkbox, Form, Input, Modal, Select, Tag, Tooltip, Typography } from 'antd';
import { useState } from 'react';

import { ADMIN, adminApi } from '../../api/admin';
import type { AdminUser, RoleRecord, UserFormValues } from '../../api/admin';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import { useList } from '../../hooks/useApi';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors, matchesField, passwordRules } from '../../utils/forms';
import { notifyError } from '../../utils/notify';

function ResetPasswordModal({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm<{ password: string; confirm: string }>();
  const mutation = useMutation({
    mutationFn: (password: string) => adminApi.resetUserPassword(user!.id, password),
    meta: { silent: true },
    onSuccess: () => {
      message.success(`Temporary password set. ${user?.full_name} must change it at next login.`);
      onClose();
    },
    onError: (error) => {
      if (!applyServerErrors(form, error)) notifyError(error, 'Could not reset password');
    },
  });

  return (
    <Modal
      title={`Reset password: ${user?.full_name ?? ''}`}
      open={user !== null}
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="Set temporary password"
      confirmLoading={mutation.isPending}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        The user will be asked to choose a new password the next time they log in.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={(v) => mutation.mutate(v.password)} preserve={false}>
        <Form.Item name="password" label="Temporary password" rules={passwordRules}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="Confirm password"
          dependencies={['password']}
          rules={[{ required: true, message: 'Confirm the password' }, matchesField('password')]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default function UsersPage() {
  const roles = useList<RoleRecord>(ADMIN.roles, { page_size: 100 });
  const roleOptions = (roles.data?.items ?? []).map((r) => ({ label: r.name, value: r.id }));
  const canEdit = usePermission('user.edit');
  const [resetting, setResetting] = useState<AdminUser | null>(null);

  return (
    <>
      <CrudPage<AdminUser, UserFormValues>
        title="Users"
        endpoint={ADMIN.users}
        permission="user"
        itemName="user"
        searchPlaceholder="Name, username, email or mobile"
        filters={[{ name: 'role_id', label: 'Role', options: roleOptions }]}
        initialValues={{ must_change_password: true }}
        errorFields={{
          USERNAME_TAKEN: 'username',
          EMAIL_TAKEN: 'email',
          MOBILE_TAKEN: 'mobile',
          INVALID_ROLE: 'role_id',
        }}
        toFormValues={(u) => ({
          full_name: u.full_name,
          username: u.username,
          email: u.email,
          mobile: u.mobile,
          role_id: u.role_id,
        })}
        toPayload={(v, record) =>
          record ? { full_name: v.full_name, email: v.email, mobile: v.mobile, role_id: v.role_id } : v
        }
        columns={[
          {
            title: 'Name',
            key: 'name',
            render: (_, u) => (
              <>
                <div>{u.full_name}</div>
                <Typography.Text type="secondary">@{u.username}</Typography.Text>
              </>
            ),
          },
          {
            title: 'Contact',
            key: 'contact',
            render: (_, u) => (
              <>
                <div>{u.email ?? '—'}</div>
                <Typography.Text type="secondary">{u.mobile ?? ''}</Typography.Text>
              </>
            ),
          },
          {
            title: 'Role',
            dataIndex: 'role_name',
            render: (name: string) => <Tag color="blue">{name}</Tag>,
          },
          {
            title: 'Last login',
            dataIndex: 'last_login_at',
            render: (v: string | null) => (v ? <DateText value={v} withTime /> : <Typography.Text type="secondary">Never</Typography.Text>),
          },
          {
            title: 'Password',
            key: 'pw',
            render: (_, u) => (u.must_change_password ? <Tag color="gold">Must change</Tag> : null),
          },
        ]}
        rowActions={(u) =>
          canEdit && (
            <Tooltip title="Set temporary password">
              <Button size="small" type="text" icon={<KeyOutlined />} aria-label="Reset password" onClick={() => setResetting(u)} />
            </Tooltip>
          )
        }
        renderForm={({ record }) => (
          <>
            <Form.Item name="full_name" label="Full name" rules={[{ required: true, whitespace: true, message: 'Enter the name' }, { max: 150 }]}>
              <Input />
            </Form.Item>
            <Form.Item
              name="username"
              label="Username"
              extra={record ? 'Usernames cannot be changed.' : '3–50 letters, digits, dot, dash or underscore.'}
              rules={[
                { required: true, message: 'Enter a username' },
                { pattern: /^[A-Za-z0-9_.-]{3,50}$/, message: '3–50 letters, digits, dot, dash or underscore' },
              ]}
            >
              <Input disabled={record !== null} autoComplete="off" />
            </Form.Item>
            <Form.Item name="email" label="Email" rules={[{ type: 'email', message: 'Enter a valid email' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="mobile" label="Mobile" rules={[{ pattern: /^\+?[0-9]{6,19}$/, message: 'Digits only, optionally starting with +' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="role_id" label="Role" rules={[{ required: true, message: 'Choose a role' }]}>
              <Select options={roleOptions} loading={roles.isPending} placeholder="Choose a role" />
            </Form.Item>
            {!record && (
              <>
                <Form.Item name="password" label="Initial password" rules={passwordRules}>
                  <Input.Password autoComplete="new-password" />
                </Form.Item>
                <Form.Item name="must_change_password" valuePropName="checked">
                  <Checkbox>Ask the user to change this password at first login</Checkbox>
                </Form.Item>
              </>
            )}
          </>
        )}
      />
      <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />
    </>
  );
}
