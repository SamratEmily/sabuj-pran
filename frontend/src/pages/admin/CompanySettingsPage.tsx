import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card, Col, Form, Image, Input, Row, Select, Skeleton } from 'antd';
import { useMemo } from 'react';

import { ADMIN, adminApi } from '../../api/admin';
import type { CompanySettings } from '../../api/admin';
import DateText from '../../components/DateText';
import ErrorState from '../../components/ErrorState';
import PageHeader from '../../components/PageHeader';
import { usePermission } from '../../hooks/usePermission';
import { applyServerErrors } from '../../utils/forms';
import { notifyError } from '../../utils/notify';

function timeZones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone');
  } catch {
    return ['Asia/Dhaka', 'UTC'];
  }
}

export default function CompanySettingsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const canEdit = usePermission('company_setting.edit');
  const [form] = Form.useForm<CompanySettings>();
  const zones = useMemo(() => timeZones().map((z) => ({ label: z, value: z })), []);

  const settings = useQuery({ queryKey: [ADMIN.companySettings], queryFn: adminApi.companySettings });
  const save = useMutation({
    mutationFn: adminApi.updateCompanySettings,
    meta: { silent: true },
    onSuccess: (data) => {
      queryClient.setQueryData([ADMIN.companySettings], data);
      message.success('Company settings saved');
    },
    onError: (error) => {
      if (!applyServerErrors(form, error, { INVALID_TIMEZONE: 'timezone' })) {
        notifyError(error, 'Could not save settings');
      }
    },
  });

  return (
    <>
      <PageHeader
        title="Company Settings"
        subtitle={settings.data?.updated_at && <>Last updated <DateText value={settings.data.updated_at} withTime /></>}
      />
      {settings.isError ? (
        <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
      ) : settings.isPending ? (
        <Skeleton active />
      ) : (
        <Card style={{ maxWidth: 880 }}>
          <Form<CompanySettings>
            // Re-initialise after save/refetch
            key={settings.dataUpdatedAt}
            form={form}
            layout="vertical"
            initialValues={settings.data}
            disabled={!canEdit || save.isPending}
            onFinish={(v) => save.mutate({ ...settings.data, ...v })}
          >
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item name="company_name" label="Company name" rules={[{ max: 150 }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="phone" label="Phone" rules={[{ max: 30 }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col xs={24}>
                <Form.Item name="address" label="Address" rules={[{ max: 500 }]}>
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="email" label="Email" rules={[{ type: 'email', message: 'Enter a valid email' }, { max: 150 }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item name="currency_symbol" label="Currency" rules={[{ required: true, whitespace: true, message: 'Required' }, { max: 10 }]}>
                  <Input />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item name="timezone" label="Time zone" rules={[{ required: true, message: 'Required' }]}>
                  <Select showSearch options={zones} />
                </Form.Item>
              </Col>
              <Col xs={24}>
                <Form.Item
                  name="invoice_footer_note"
                  label="Invoice footer note"
                  extra="Printed at the bottom of invoices. The invoice number prefix is set in Document Numbering."
                  rules={[{ max: 500 }]}
                >
                  <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={16}>
                <Form.Item name="logo_url" label="Logo URL" rules={[{ type: 'url', message: 'Enter a full URL (https://…)' }, { max: 500 }]}>
                  <Input placeholder="https://…" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item noStyle shouldUpdate={(a, b) => a.logo_url !== b.logo_url}>
                  {({ getFieldValue }) =>
                    getFieldValue('logo_url') ? (
                      <Image src={getFieldValue('logo_url')} alt="Logo preview" height={64} style={{ objectFit: 'contain' }} />
                    ) : null
                  }
                </Form.Item>
              </Col>
            </Row>
            {canEdit && (
              <Button type="primary" htmlType="submit" loading={save.isPending}>
                Save settings
              </Button>
            )}
          </Form>
        </Card>
      )}
    </>
  );
}
