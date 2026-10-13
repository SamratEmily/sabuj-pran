import { DownOutlined, KeyOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { Avatar, Badge, Dropdown, Flex, Layout, Menu, Tag, Typography, theme } from 'antd';
import type { MenuProps } from 'antd';
import { useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router';

import { usePendingCount } from '../api/approvals';
import { useAuth } from '../hooks/useAuth';
import { CHANGE_PASSWORD_PATH } from '../routes/guards';
import { HOME_ICON, NAVIGATION, filterNavigation, navLeaves } from '../routes/navigation';
import type { NavItem } from '../routes/navigation';

const COLLAPSED_KEY = 'bms_sider_collapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

/** `badges`: counts shown next to menu entries, by nav key (e.g. pending approvals). */
function toMenuItems(items: NavItem[], badges: Record<string, number> = {}): MenuProps['items'] {
  const label = (item: NavItem) =>
    badges[item.key] ? (
      <Flex justify="space-between" align="center" gap={8}>
        {item.label}
        <Badge count={badges[item.key]} size="small" />
      </Flex>
    ) : (
      item.label
    );
  return items.map((item) => {
    const childBadge = item.children?.some((c) => badges[c.key]);
    return item.children
      ? { key: item.key, icon: item.icon, label: childBadge ? <>{item.label} <Badge dot style={{ marginLeft: 4 }} /></> : item.label, children: toMenuItems(item.children, badges) }
      : { key: item.path!, icon: item.icon, label: label(item) };
  });
}

/** The leaf whose path is the longest prefix of the current URL. */
function activeLeaf(items: NavItem[], pathname: string): NavItem | undefined {
  return navLeaves(items)
    .filter((l) => l.path && (pathname === l.path || pathname.startsWith(`${l.path}/`)))
    .sort((a, b) => b.path!.length - a.path!.length)[0];
}

function groupOf(items: NavItem[], leaf?: NavItem): string | undefined {
  return items.find((g) => g.children?.some((c) => c.key === leaf?.key))?.key;
}

export default function AppLayout() {
  const { user, permissions, logout } = useAuth();
  const { token } = theme.useToken();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const visible = useMemo(() => filterNavigation(NAVIGATION, permissions), [permissions]);
  const pendingCount = usePendingCount(permissions.has('approval.view'));
  const active = activeLeaf(visible, location.pathname);
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const group = groupOf(visible, active);
    return group ? [group] : [];
  });

  const onCollapse = (value: boolean) => {
    setCollapsed(value);
    try {
      localStorage.setItem(COLLAPSED_KEY, value ? '1' : '0');
    } catch {
      // ignore
    }
  };

  const userMenu: MenuProps = {
    items: [
      { key: '/profile', icon: <UserOutlined />, label: 'My Profile' },
      { key: CHANGE_PASSWORD_PATH, icon: <KeyOutlined />, label: 'Change Password' },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: 'Log out', danger: true },
    ],
    onClick: ({ key }) => (key === 'logout' ? void logout() : navigate(key)),
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={onCollapse}
        breakpoint="lg"
        width={240}
        style={{ position: 'sticky', top: 0, height: '100vh', overflow: 'auto' }}
      >
        <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 10, height: 64, padding: '0 24px', color: '#fff' }}>
          <span style={{ fontSize: 20 }}>{HOME_ICON}</span>
          {!collapsed && <strong style={{ fontSize: 16, whiteSpace: 'nowrap' }}>Business Manager</strong>}
        </Link>
        <Menu
          theme="dark"
          mode="inline"
          items={toMenuItems(visible, { approvals: pendingCount.data ?? 0 })}
          selectedKeys={active?.path ? [active.path] : []}
          // Collapsed menus show groups as hover pop-ups: don't force them open.
          {...(collapsed ? {} : { openKeys, onOpenChange: setOpenKeys })}
          onClick={({ key }) => navigate(key)}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header
          style={{
            background: token.colorBgContainer,
            padding: '0 16px',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <Flex justify="flex-end" align="center" style={{ height: '100%' }}>
            <Dropdown menu={userMenu} trigger={['click']}>
              <Flex align="center" gap={8} style={{ cursor: 'pointer' }} role="button" aria-label="User menu">
                <Avatar icon={<UserOutlined />} style={{ background: token.colorPrimary }} />
                <Typography.Text strong>{user?.full_name}</Typography.Text>
                <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                  {user?.role}
                </Tag>
                <DownOutlined style={{ fontSize: 10 }} />
              </Flex>
            </Dropdown>
          </Flex>
        </Layout.Header>
        <Layout.Content style={{ margin: 16 }}>
          <div style={{ background: token.colorBgContainer, borderRadius: token.borderRadiusLG, padding: 24, minHeight: '100%' }}>
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
