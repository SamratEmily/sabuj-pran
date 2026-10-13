import { Card, Flex, Typography, theme } from 'antd';
import { Outlet } from 'react-router';

import { HOME_ICON } from '../routes/navigation';

/** Centered card for login / forgot / reset password. */
export default function AuthLayout() {
  const { token } = theme.useToken();
  return (
    <Flex justify="center" align="center" style={{ minHeight: '100vh', padding: 16, background: token.colorBgLayout }}>
      <Card style={{ width: 400, maxWidth: '100%' }}>
        <Flex vertical align="center" gap={4} style={{ marginBottom: 24 }}>
          <span style={{ fontSize: 32, color: token.colorPrimary }}>{HOME_ICON}</span>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Business Manager
          </Typography.Title>
        </Flex>
        <Outlet />
      </Card>
    </Flex>
  );
}
