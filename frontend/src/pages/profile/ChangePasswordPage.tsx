import { useMutation } from '@tanstack/react-query';
import { Alert, App, Button, Card, Form, Input } from 'antd';
import { useNavigate } from 'react-router';

import { authApi } from '../../api/auth';
import PageHeader from '../../components/PageHeader';
import { useAuth } from '../../hooks/useAuth';
import { applyServerErrors, matchesField, passwordRules } from '../../utils/forms';
import { notifyError } from '../../utils/notify';

interface ChangePasswordForm {
  current_password: string;
  new_password: string;
  confirm: string;
}

export default function ChangePasswordPage() {
  const { user, setUser } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<ChangePasswordForm>();
  const mutation = useMutation({
    mutationFn: (v: ChangePasswordForm) => authApi.changePassword(v.current_password, v.new_password),
    meta: { silent: true },
    onSuccess: () => {
      message.success('Password changed');
      form.resetFields();
      if (user?.must_change_password) {
        setUser({ ...user, must_change_password: false });
        navigate('/', { replace: true });
      }
    },
    onError: (error) => {
      const mapped = applyServerErrors(form, error, {
        INVALID_CURRENT_PASSWORD: 'current_password',
        PASSWORD_UNCHANGED: 'new_password',
      });
      if (!mapped) notifyError(error, 'Could not change password');
    },
  });

  return (
    <>
      <PageHeader title="Change Password" />
      <Card style={{ maxWidth: 560 }}>
        {user?.must_change_password && (
          <Alert type="warning" showIcon title="Please set a new password before continuing." style={{ marginBottom: 16 }} />
        )}
        <Form<ChangePasswordForm> form={form} layout="vertical" onFinish={(v) => mutation.mutate(v)} disabled={mutation.isPending}>
          <Form.Item name="current_password" label="Current password" rules={[{ required: true, message: 'Enter your current password' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="new_password" label="New password" rules={passwordRules} hasFeedback>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="Confirm new password"
            dependencies={['new_password']}
            rules={[{ required: true, message: 'Confirm the new password' }, matchesField('new_password')]}
            hasFeedback
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            Change password
          </Button>
        </Form>
      </Card>
    </>
  );
}
