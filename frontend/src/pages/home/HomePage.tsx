import { useQuery } from '@tanstack/react-query';
import { Button, Card, Descriptions, Spin, Tag } from 'antd';

import { getHealth } from '../../api/health';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import PageHeader from '../../components/PageHeader';
import { useAuth } from '../../hooks/useAuth';
import { usePermission } from '../../hooks/usePermission';
import DashboardPage from '../dashboard/DashboardPage';

/** Home route: the management dashboard for users who may see it, else a welcome page. */
export default function HomePage() {
  const canDashboard = usePermission('dashboard.view');
  return canDashboard ? <DashboardPage /> : <WelcomePage />;
}

function WelcomePage() {
  const { user } = useAuth();
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth });

  return (
    <>
      <PageHeader title={`Welcome, ${user?.full_name ?? ''}`} subtitle="Use the menu on the left to get started." />
      <Card
        title="System status"
        style={{ maxWidth: 560 }}
        extra={
          <Button onClick={() => health.refetch()} loading={health.isFetching}>
            Refresh
          </Button>
        }
      >
        {health.isPending ? (
          <Spin />
        ) : health.isError ? (
          <ErrorState error={health.error} title="API unreachable" />
        ) : (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="API">
              <Tag color={health.data.status === 'ok' ? 'green' : 'red'}>{health.data.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Database">
              <Tag color={health.data.db ? 'green' : 'red'}>{health.data.db ? 'connected' : 'down'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Checked at">
              <DateText value={new Date(health.dataUpdatedAt).toISOString()} withTime />
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </>
  );
}
