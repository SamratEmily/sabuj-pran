import { CheckOutlined, CloseOutlined, SendOutlined, SwapOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Form, Modal, Select, Tooltip, Typography } from 'antd';
import dayjs from 'dayjs';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import { errorMessage } from '../../api/client';
import { useLookups } from '../../api/master';
import { SALES, salesApi } from '../../api/sales';
import type { Quotation } from '../../api/sales';
import ConfirmButton from '../../components/ConfirmButton';
import CrudPage from '../../components/CrudPage';
import DateText from '../../components/DateText';
import { newLine } from '../../components/DocLineItems';
import MoneyText from '../../components/MoneyText';
import StatusTag from '../../components/StatusTag';
import { usePermission } from '../../hooks/usePermission';
import { notifyError } from '../../utils/notify';
import SalesDocForm, { linesPayload, SALES_ERROR_FIELDS, toLines, useCustomerOptions } from './SalesDocForm';
import type { SalesDocValues } from './SalesDocForm';

const STATUS_OPTIONS = ['draft', 'sent', 'accepted', 'rejected', 'converted'].map((s) => ({
  label: s.charAt(0).toUpperCase() + s.slice(1),
  value: s,
}));

const right = (text: string) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

function ConvertModal({ quotation, onClose }: { quotation: Quotation | null; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const lookups = useLookups();
  const [warehouseId, setWarehouseId] = useState<number | undefined>();
  const mutation = useMutation({
    mutationFn: () => salesApi.convert(quotation!.id, warehouseId),
    meta: { silent: true },
    onSuccess: async (so) => {
      message.success(`${quotation!.qt_number} converted to ${so.so_number}`);
      onClose();
      await Promise.all([SALES.quotations, SALES.orders].map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
      navigate(`${SALES.orders}/${so.id}`);
    },
  });
  const warehouses = lookups.data?.warehouses ?? [];
  return (
    <Modal
      title={quotation ? `Convert ${quotation.qt_number} to a sales order` : ''}
      open={quotation !== null}
      onCancel={onClose}
      okText="Create sales order"
      confirmLoading={mutation.isPending}
      onOk={() => mutation.mutate()}
      afterOpenChange={(open) => {
        if (open) {
          mutation.reset();
          setWarehouseId(warehouses.find((w) => w.is_default)?.id);
        }
      }}
      destroyOnHidden
    >
      {mutation.isError && <Alert type="error" showIcon title="Could not convert" description={errorMessage(mutation.error)} style={{ marginBottom: 12 }} />}
      <Typography.Paragraph type="secondary">
        The lines, prices and discount are copied into a new draft order. The quotation is marked converted and can no longer be edited.
      </Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item label="Deliver from warehouse" required>
          <Select value={warehouseId} onChange={setWarehouseId} options={warehouses.map((w) => ({ label: w.name, value: w.id }))} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function StatusActions({ q, onConvert }: { q: Quotation; onConvert: () => void }) {
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const canEdit = usePermission('quotation.edit');
  const canConvert = usePermission('sales_order.create');
  const run = async (action: 'send' | 'accept' | 'reject') => {
    try {
      const res = await salesApi.quotationAction(q.id, action);
      message.success(`${res.qt_number} ${res.status}`);
      await queryClient.invalidateQueries({ queryKey: [SALES.quotations] });
    } catch (error) {
      notifyError(error, 'Could not update the quotation');
    }
  };
  return (
    <>
      {canEdit && q.status === 'draft' && (
        <ConfirmButton size="small" type="text" icon={<SendOutlined />} aria-label="Mark sent" confirm={`Mark ${q.qt_number} as sent?`} description="Sent quotations can no longer be edited." onConfirm={() => run('send')} />
      )}
      {canEdit && q.status === 'sent' && (
        <>
          <ConfirmButton size="small" type="text" icon={<CheckOutlined />} aria-label="Accept" confirm={`Customer accepted ${q.qt_number}?`} onConfirm={() => run('accept')} />
          <ConfirmButton size="small" type="text" danger icon={<CloseOutlined />} aria-label="Reject" confirm={`Customer rejected ${q.qt_number}?`} onConfirm={() => run('reject')} />
        </>
      )}
      {canConvert && ['draft', 'sent', 'accepted'].includes(q.status) && (
        <Tooltip title="Convert to Sales Order">
          <Button size="small" type="text" icon={<SwapOutlined />} aria-label="Convert to Sales Order" onClick={onConvert} />
        </Tooltip>
      )}
    </>
  );
}

export default function QuotationsPage() {
  const customers = useCustomerOptions();
  const [converting, setConverting] = useState<Quotation | null>(null);
  const canConvert = usePermission('sales_order.create');

  return (
    <>
      <CrudPage<Quotation, SalesDocValues>
        title="Quotations"
        endpoint={SALES.quotations}
        permission="quotation"
        itemName="quotation"
        searchPlaceholder="Quotation number or customer"
        deactivatable={false}
        dateRangeFilter
        canEditRow={(q) => q.status === 'draft'}
        formWidth={1080}
        filters={[
          { name: 'customer_id', label: 'Customer', options: customers.options, width: 220 },
          { name: 'status', label: 'Status', options: STATUS_OPTIONS },
        ]}
        initialValues={{ date: dayjs(), discount: '0', notes: '', items: [newLine()] }}
        errorFields={SALES_ERROR_FIELDS}
        toFormValues={(q) => ({
          customer_id: q.customer_id,
          date: dayjs(q.quote_date),
          second_date: q.valid_until ? dayjs(q.valid_until) : null,
          discount: q.discount,
          notes: q.notes,
          items: toLines(q.items),
        })}
        toPayload={(v) => ({
          ...linesPayload(v),
          quote_date: v.date.format('YYYY-MM-DD'),
          valid_until: v.second_date ? v.second_date.format('YYYY-MM-DD') : null,
        })}
        rowActions={(q) => <StatusActions q={q} onConvert={() => setConverting(q)} />}
        formFooterExtra={({ record, close }) =>
          record &&
          canConvert && (
            <Button icon={<SwapOutlined />} onClick={() => { close(); setConverting(record); }}>
              Convert to Sales Order
            </Button>
          )
        }
        columns={[
          { title: 'Quotation', dataIndex: 'qt_number', render: (v: string) => <strong>{v}</strong> },
          { title: 'Date', dataIndex: 'quote_date', render: (v: string) => <DateText value={v} /> },
          { title: 'Valid until', dataIndex: 'valid_until', render: (v: string | null) => <DateText value={v} /> },
          { title: 'Customer', key: 'c', render: (_, q) => <>{q.customer_code} {q.customer_name}</> },
          { title: right('Total'), dataIndex: 'total', render: (v: string) => <MoneyText value={v} strong /> },
          {
            title: 'Status',
            key: 'status',
            render: (_, q) => (
              <>
                <StatusTag status={q.status} />
                {q.converted_order_id && <Link to={`${SALES.orders}/${q.converted_order_id}`}>{q.converted_order_number}</Link>}
              </>
            ),
          },
        ]}
        renderForm={() => <SalesDocForm dateLabel="Quote date" secondDateLabel="Valid until" />}
      />
      <ConvertModal quotation={converting} onClose={() => setConverting(null)} />
    </>
  );
}
