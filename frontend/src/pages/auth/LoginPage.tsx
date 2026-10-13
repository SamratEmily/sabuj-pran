import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { Alert, Button, Form, Input } from 'antd';
import { Link } from 'react-router';

import { errorMessage } from '../../api/client';
import { useAuth } from '../../hooks/useAuth';

interface LoginForm {
  identifier: string;
  password: string;
}

export default function LoginPage() {
  const { login } = useAuth();
  // On success the user is set and GuestOnlyRoute redirects to the requested page.
  const mutation = useMutation({
    mutationFn: (v: LoginForm) => login(v.identifier.trim(), v.password),
    meta: { silent: true },
  });

  return (
    <Form<LoginForm> layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
      {mutation.isError && (
        <Alert type="error" showIcon title={errorMessage(mutation.error)} style={{ marginBottom: 16 }} />
      )}
      <Form.Item
        name="identifier"
        label="Username, email or mobile"
        rules={[{ required: true, whitespace: true, message: 'Enter your username, email or mobile' }]}
      >
        <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
      </Form.Item>
      <Form.Item name="password" label="Password" rules={[{ required: true, message: 'Enter your password' }]}>
        <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={mutation.isPending}>
        Log in
      </Button>
      <div style={{ textAlign: 'center', marginTop: 16 }}>
        <Link to="/forgot-password">Forgot password?</Link>
      </div>
    </Form>
  );
}
