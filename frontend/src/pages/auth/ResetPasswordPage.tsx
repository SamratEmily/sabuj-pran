import { useMutation } from '@tanstack/react-query';
import { Alert, App, Button, Form, Input } from 'antd';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { authApi } from '../../api/auth';
import { errorMessage } from '../../api/client';
import { applyServerErrors, matchesField, passwordRules } from '../../utils/forms';

interface ResetForm {
  token: string;
  new_password: string;
  confirm: string;
}

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm<ResetForm>();
  const mutation = useMutation({
    mutationFn: (v: ResetForm) => authApi.resetPassword(v.token.trim(), v.new_password),
    meta: { silent: true },
    onSuccess: () => {
      message.success('Password reset. Please log in with your new password.');
      navigate('/login', { replace: true });
    },
    onError: (error) => applyServerErrors(form, error),
  });

  return (
    <Form<ResetForm>
      form={form}
      layout="vertical"
      requiredMark={false}
      initialValues={{ token: params.get('token') ?? '' }}
      onFinish={(v) => mutation.mutate(v)}
    >
      {mutation.isError && (
        <Alert type="error" showIcon title={errorMessage(mutation.error)} style={{ marginBottom: 16 }} />
      )}
      <Form.Item name="token" label="Reset token" rules={[{ required: true, whitespace: true, message: 'Enter the reset token' }]}>
        <Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} />
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
      <Button type="primary" htmlType="submit" block loading={mutation.isPending}>
        Reset password
      </Button>
      <div style={{ textAlign: 'center', marginTop: 16 }}>
        <Link to="/login">Back to login</Link>
      </div>
    </Form>
  );
}
