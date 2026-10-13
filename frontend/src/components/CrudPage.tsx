import { EditOutlined, PlusOutlined, StopOutlined, UndoOutlined } from '@ant-design/icons';
import { App, Button, DatePicker, Drawer, Flex, Form, Input, Modal, Select, Space, Table } from 'antd';
import type { FormInstance, TableProps } from 'antd';
import type { Dayjs } from 'dayjs';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { useList, useRecordAction, useSave } from '../hooks/useApi';
import { usePermission } from '../hooks/usePermission';
import { errorCode, errorMessage } from '../api/client';
import { applyServerErrors } from '../utils/forms';
import { notifyError } from '../utils/notify';
import ConfirmButton from './ConfirmButton';
import ErrorState from './ErrorState';
import PageHeader from './PageHeader';
import StatusTag from './StatusTag';

export interface CrudRecord {
  id: number;
  is_active?: boolean;
}

export interface CrudFilter {
  /** Query param name sent to the list endpoint. */
  name: string;
  label: string;
  options: { label: string; value: string | number | boolean }[];
  width?: number;
}

export interface CrudPageProps<T extends CrudRecord, TForm extends object> {
  title: string;
  /** e.g. "/products": GET list, POST create, PUT /{id}, POST /{id}/deactivate|activate. */
  endpoint: string;
  /** Permission prefix, e.g. "product" -> product.view/create/edit/delete. */
  permission: string;
  columns: NonNullable<TableProps<T>['columns']>;
  /** Singular name used in buttons and titles, e.g. "product". */
  itemName?: string;
  searchPlaceholder?: string;
  filters?: CrudFilter[];
  /** Form.Item fields for create/edit. */
  renderForm: (ctx: { form: FormInstance<TForm>; record: T | null }) => ReactNode;
  /** Record -> form values when editing (default: the record itself). */
  toFormValues?: (record: T) => Partial<TForm>;
  /** Form values -> request body (default: the values). */
  toPayload?: (values: TForm, record: T | null) => unknown;
  /** Defaults for a new record. */
  initialValues?: Partial<TForm>;
  formMode?: 'drawer' | 'modal';
  formWidth?: number;
  /** Show status column/filter and deactivate/activate actions (default true). */
  deactivatable?: boolean;
  /** Show the "New" button (default true; still needs `<permission>.create`). */
  creatable?: boolean;
  /** Show the search box (default true). */
  searchable?: boolean;
  /** Extra buttons in each row's Actions cell. */
  rowActions?: (record: T) => ReactNode;
  /** Business error codes mapped to form fields, e.g. { USERNAME_TAKEN: 'username' }. */
  errorFields?: Record<string, string>;
  /** Other query-key prefixes to refresh after any change (e.g. lookups). */
  invalidates?: readonly string[];
  /** Show the row Edit action (default true). Documents that can't be edited turn it off. */
  editable?: boolean;
  /** Label of the form's submit button (default "Save"). */
  saveLabel?: string;
  /** Called with the server's response after a successful create/update. */
  onSaved?: (saved: T, created: boolean) => void;
  /** Per-row edit permission on top of `<permission>.edit` (e.g. only drafts). */
  canEditRow?: (record: T) => boolean;
  /** Replace the default POST/PUT (e.g. a different endpoint for some submissions). */
  submit?: (data: unknown, record: T | null) => Promise<T>;
  /** Show a date range filter sent as `from` / `to` (YYYY-MM-DD). */
  dateRangeFilter?: boolean;
  /** Rendered between the page header and the filters (e.g. summary cards). */
  headerExtra?: ReactNode;
  /** Open the "New" form when this changes, pre-filled with these values (e.g. from a link).
   *  Pass a memoized object. */
  openWith?: Partial<TForm> | null;
  /** Extra buttons on the left of the form footer (e.g. "Convert" on an existing record). */
  formFooterExtra?: (ctx: { record: T | null; close: () => void }) => ReactNode;
  /** Start with this search (e.g. a document number from a link). */
  initialSearch?: string;
}

const STATUS_FILTER: CrudFilter = {
  name: 'is_active',
  label: 'Status',
  options: [
    { label: 'Active', value: true },
    { label: 'Inactive', value: false },
  ],
  width: 130,
};

export default function CrudPage<T extends CrudRecord, TForm extends object = Record<string, unknown>>({
  title,
  endpoint,
  permission,
  columns,
  itemName = 'record',
  searchPlaceholder = 'Search',
  filters = [],
  renderForm,
  toFormValues,
  toPayload,
  initialValues,
  formMode = 'drawer',
  formWidth = 520,
  deactivatable = true,
  creatable = true,
  searchable = true,
  rowActions,
  errorFields,
  invalidates,
  editable = true,
  saveLabel = 'Save',
  onSaved,
  canEditRow,
  submit,
  dateRangeFilter,
  headerExtra,
  openWith,
  formFooterExtra,
  initialSearch = '',
}: CrudPageProps<T, TForm>) {
  const queryClient = useQueryClient();
  const { message, modal } = App.useApp();
  const canCreate = usePermission(`${permission}.create`);
  const canEdit = usePermission(`${permission}.edit`) && editable;
  const canDelete = usePermission(`${permission}.delete`);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState(initialSearch);
  const [filterValues, setFilterValues] = useState<Record<string, string | number | boolean | undefined>>({});
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [editing, setEditing] = useState<{ record: T | null; prefill?: Partial<TForm> } | null>(null);

  const [form] = Form.useForm<TForm>();
  const list = useList<T>(endpoint, {
    page,
    page_size: pageSize,
    search,
    ...filterValues,
    from: range?.[0]?.format('YYYY-MM-DD'),
    to: range?.[1]?.format('YYYY-MM-DD'),
  });
  const save = useSave<unknown>(endpoint, { silent: true, invalidates });
  const deactivate = useRecordAction(endpoint, 'deactivate', { silent: true, invalidates });
  const activate = useRecordAction(endpoint, 'activate', { invalidates });

  // Backend answers 409 CONFIRM_REQUIRED when the record is still in use (e.g. a unit used
  // by active products): ask, then retry with ?force=true.
  const handleDeactivate = async (id: number) => {
    try {
      await deactivate.mutateAsync(id);
      message.success('Deactivated');
    } catch (error) {
      if (errorCode(error) !== 'CONFIRM_REQUIRED') {
        notifyError(error, 'Could not deactivate');
        return;
      }
      modal.confirm({
        title: `Deactivate this ${itemName}?`,
        content: errorMessage(error),
        okText: 'Deactivate anyway',
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await deactivate.mutateAsync({ id, params: { force: true } });
            message.success('Deactivated');
          } catch (retryError) {
            notifyError(retryError, 'Could not deactivate');
          }
        },
      });
    }
  };

  // Each time the form opens, start from that record's values (or the defaults for "New"),
  // never from whatever was typed last time.
  // (A form opened from a link mounts fresh with its prefill, before the form is connected.)
  useEffect(() => {
    if (editing && !editing.prefill) form.resetFields();
  }, [editing, form]);

  useEffect(() => {
    if (openWith && canCreate) setEditing({ record: null, prefill: openWith });
  }, [openWith, canCreate]);

  const allFilters = deactivatable ? [...filters, STATUS_FILTER] : filters;
  const record = editing?.record ?? null;

  const openForm = (r: T | null) => {
    setEditing({ record: r });
  };

  const handleSubmit = async (values: TForm) => {
    try {
      const data = toPayload ? toPayload(values, record) : values;
      let saved: T;
      if (submit) {
        saved = await submit(data, record);
        await Promise.all([endpoint, ...(invalidates ?? [])].map((key) => queryClient.invalidateQueries({ queryKey: [key] })));
      } else {
        saved = (await save.mutateAsync({ id: record?.id, data })) as T;
      }
      message.success(record ? `${capitalize(itemName)} updated` : `${capitalize(itemName)} created`);
      setEditing(null);
      onSaved?.(saved, !record);
    } catch (error) {
      if (!applyServerErrors(form, error, errorFields)) notifyError(error, 'Could not save');
    }
  };

  const actionColumn: NonNullable<TableProps<T>['columns']>[number] = {
    title: 'Actions',
    key: '__actions',
    width: 140,
    fixed: 'right',
    render: (_, r) => (
      <Space size={4}>
        {canEdit && (!canEditRow || canEditRow(r)) && (
          <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openForm(r)} aria-label="Edit" />
        )}
        {rowActions?.(r)}
        {canDelete && deactivatable && r.is_active !== false && (
          <ConfirmButton
            size="small"
            type="text"
            danger
            icon={<StopOutlined />}
            aria-label="Deactivate"
            confirm={`Deactivate this ${itemName}?`}
            description="It will be hidden from new documents. History is kept."
            onConfirm={() => handleDeactivate(r.id)}
          />
        )}
        {canDelete && deactivatable && r.is_active === false && (
          <ConfirmButton
            size="small"
            type="text"
            icon={<UndoOutlined />}
            aria-label="Activate"
            confirm={`Activate this ${itemName}?`}
            onConfirm={() => activate.mutateAsync(r.id).then(() => message.success('Activated'))}
          />
        )}
      </Space>
    ),
  };

  const statusColumn: NonNullable<TableProps<T>['columns']>[number] = {
    title: 'Status',
    key: '__status',
    width: 100,
    render: (_, r) => <StatusTag status={r.is_active === false ? 'inactive' : 'active'} />,
  };

  const tableColumns = [
    ...columns,
    ...(deactivatable ? [statusColumn] : []),
    ...(canEdit || (canDelete && deactivatable) || rowActions ? [actionColumn] : []),
  ];

  const formTitle = record ? `Edit ${itemName}` : `New ${itemName}`;
  const formBody = (
    <Form<TForm>
      key={record?.id ?? 'new'}
      form={form}
      layout="vertical"
      initialValues={(record ? (toFormValues ? toFormValues(record) : record) : { ...initialValues, ...editing?.prefill }) as TForm}
      onFinish={handleSubmit}
      disabled={save.isPending}
    >
      {renderForm({ form, record })}
    </Form>
  );
  const formFooter = (
    <Flex justify="flex-end" gap={8}>
      {formFooterExtra && <div style={{ marginRight: 'auto' }}>{formFooterExtra({ record, close: () => setEditing(null) })}</div>}
      <Button onClick={() => setEditing(null)}>Cancel</Button>
      <Button type="primary" loading={save.isPending} onClick={() => form.submit()}>
        {saveLabel}
      </Button>
    </Flex>
  );

  return (
    <>
      <PageHeader
        title={title}
        actions={
          canCreate && creatable && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm(null)}>
              New {itemName}
            </Button>
          )
        }
      />

      {headerExtra}

      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        {searchable && (
        <Input.Search
          allowClear
          defaultValue={initialSearch}
          placeholder={searchPlaceholder}
          style={{ width: 280, maxWidth: '100%' }}
          onSearch={(value) => {
            setSearch(value.trim());
            setPage(1);
          }}
        />
        )}
        {dateRangeFilter && (
          <DatePicker.RangePicker
            allowEmpty={[true, true]}
            value={range}
            onChange={(v) => {
              setRange(v);
              setPage(1);
            }}
          />
        )}
        {allFilters.map((f) => (
          <Select
            key={f.name}
            allowClear
            placeholder={f.label}
            options={f.options.map((o) => ({ label: o.label, value: String(o.value) }))}
            style={{ width: f.width ?? 180 }}
            onChange={(value?: string) => {
              const option = f.options.find((o) => String(o.value) === value);
              setFilterValues((prev) => ({ ...prev, [f.name]: option?.value }));
              setPage(1);
            }}
          />
        ))}
      </Flex>

      {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}

      <Table<T>
        rowKey="id"
        size="middle"
        columns={tableColumns}
        dataSource={list.data?.items ?? []}
        loading={list.isFetching}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: list.isError ? 'Could not load data' : `No ${itemName}s found` }}
        pagination={{
          current: page,
          pageSize,
          total: list.data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `${total} total`,
          onChange: (p, ps) => {
            setPage(ps !== pageSize ? 1 : p);
            setPageSize(ps);
          },
        }}
      />

      {formMode === 'drawer' ? (
        <Drawer
          title={formTitle}
          open={editing !== null}
          onClose={() => setEditing(null)}
          size={formWidth}
          destroyOnHidden
          footer={formFooter}
        >
          {formBody}
        </Drawer>
      ) : (
        <Modal
          title={formTitle}
          open={editing !== null}
          onCancel={() => setEditing(null)}
          width={formWidth}
          destroyOnHidden
          footer={formFooter}
        >
          {formBody}
        </Modal>
      )}
    </>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
