import { Table } from 'antd';
import type { TableProps } from 'antd';
import type { ReactNode } from 'react';

import ErrorState from './ErrorState';

/** The parts of a list query (`useList`) the table needs. */
export interface PagedQuery<T> {
  data?: { items: readonly T[]; total: number };
  isFetching: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

interface Props<T> extends Omit<TableProps<T>, 'pagination' | 'loading' | 'dataSource' | 'locale'> {
  query: PagedQuery<T>;
  page: number;
  pageSize: number;
  /** Called with the new page (already reset to 1 when the page size changed). */
  onPageChange: (page: number, pageSize: number) => void;
  emptyText: ReactNode;
  /** Word after the total, e.g. "entries" -> "42 entries". */
  totalLabel?: string;
  /** Rows to show instead of `query.data.items` (e.g. with a synthetic opening row). */
  dataSource?: readonly T[];
}

/** Server-paginated table with the standard loading, empty and error states. */
export default function PagedTable<T extends object>({
  query,
  page,
  pageSize,
  onPageChange,
  emptyText,
  totalLabel = 'total',
  dataSource,
  ...tableProps
}: Props<T>) {
  return (
    <>
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      <Table<T>
        rowKey="id"
        size="middle"
        scroll={{ x: 'max-content' }}
        {...tableProps}
        dataSource={dataSource ?? query.data?.items ?? []}
        loading={query.isFetching}
        locale={{ emptyText: query.isError ? 'Could not load data' : emptyText }}
        pagination={{
          current: page,
          pageSize,
          total: query.data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (t) => `${t} ${totalLabel}`,
          onChange: (p, ps) => onPageChange(ps !== pageSize ? 1 : p, ps),
        }}
      />
    </>
  );
}
