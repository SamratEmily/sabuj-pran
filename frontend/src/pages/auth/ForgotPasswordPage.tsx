import { useMutation } from '@tanstack/react-query';
import { Alert, Button, Form, Input, Typography } from 'antd';
import { Link } from 'react-router';

import { authApi } from '../../api/auth';
import { errorMessage } from '../../api/client';

export default function ForgotPasswordPage() {
  const mutation = useMutation({
    mutationFn: (identifier: string) => authApi.forgotPassword(identifier.trim()),
    meta: { silent: true },
  });
  const token = mutation.data?.reset_token;

  return (
    <>
      <Typography.Paragraph type="secondary">
        Enter your username, email or mobile. If an account matches, you will get instructions to reset your
        password.
      </Typography.Paragraph>

      {mutation.isError && (
        <Alert type="error" showIcon title={errorMessage(mutation.error)} style={{ marginBottom: 16 }} />
      )}

      {mutation.isSuccess ? (
        <>
          <Alert type="success" showIcon title={mutation.data.message} style={{ marginBottom: 16 }} />
          {token && (
            <Alert
              type="warning"
              showIcon
              title="Development mode: no email is sent"
              description={
                <>
                  <Typography.Paragraph style={{ marginBottom: 8 }}>
                    Reset token (valid for 30 minutes, single use):
                  </Typography.Paragraph>
                  <Typography.Text code copyable style={{ wordBreak: 'break-all' }}>
                    {token}
                  </Typography.Text>
                  <div style={{ marginTop: 12 }}>
                    <Link to={`/reset-password?token=${encodeURIComponent(token)}`}>Reset password now →</Link>
                  </div>
                </>
              }
              style={{ marginBottom: 16 }}
            />
          )}
        </>
      ) : (
        <Form layout="vertical" requiredMark={false} onFinish={(v: { identifier: string }) => mutation.mutate(v.identifier)}>
          <Form.Item
            name="identifier"
            label="Username, email or mobile"
            rules={[{ required: true, whitespace: true, message: 'Enter your username, email or mobile' }]}
          >
            <Input autoFocus />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={mutation.isPending}>
            Send reset instructions
          </Button>
        </Form>
      )}

      <div style={{ textAlign: 'center', marginTop: 16 }}>
        <Link to="/login">Back to login</Link>
      </div>
    </>
  );
}
