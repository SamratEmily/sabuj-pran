import { useMutation } from '@tanstack/react-query';
import { App, Button, Card, Descriptions, Form, Input } from 'antd';

import { authApi } from '../../api/auth';
import type { ProfileInput } from '../../api/auth';
import PageHeader from '../../components/PageHeader';
import { useAuth } from '../../hooks/useAuth';
import { applyServerErrors } from '../../utils/forms';
import { notifyError } from '../../utils/notify';

export default function ProfilePage() {
  const { user, setUser } = useAuth();
  const { message } = App.useApp();
  const [form] = Form.useForm<ProfileInput>();
  const mutation = useMutation({
    mutationFn: authApi.updateMe,
    meta: { silent: true },
    onSuccess: (updated) => {
      setUser(updated);
      form.setFieldsValue(updated);
      message.success('Profile updated');
    },
    onError: (error) => {
      if (!applyServerErrors(form, error, { EMAIL_TAKEN: 'email', MOBILE_TAKEN: 'mobile' })) {
        notifyError(error, 'Could not save profile');
      }
    },
  });

  if (!user) return null;

  return (
    <>
      <PageHeader title="My Profile" />
      <Card style={{ maxWidth: 560 }}>
        <Descriptions column={1} size="small" style={{ marginBottom: 24 }}>
          <Descriptions.Item label="Username">{user.username}</Descriptions.Item>
          <Descriptions.Item label="Role">{user.role}</Descriptions.Item>
        </Descriptions>
        <Form<ProfileInput>
          form={form}
          layout="vertical"
          initialValues={{ full_name: user.full_name, email: user.email, mobile: user.mobile }}
          onFinish={(v) => mutation.mutate(v)}
          disabled={mutation.isPending}
        >
          <Form.Item
            name="full_name"
            label="Full name"
            rules={[{ required: true, whitespace: true, message: 'Enter your name' }, { max: 150 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="email" label="Email" rules={[{ type: 'email', message: 'Enter a valid email' }, { max: 150 }]}>
            <Input autoComplete="email" />
          </Form.Item>
          <Form.Item
            name="mobile"
            label="Mobile"
            rules={[{ pattern: /^\+?[0-9]{6,19}$/, message: 'Digits only, optionally starting with +' }]}
          >
            <Input autoComplete="tel" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={mutation.isPending}>
            Save changes
          </Button>
        </Form>
      </Card>
    </>
  );
}
