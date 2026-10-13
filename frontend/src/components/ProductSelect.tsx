import { Select } from 'antd';
import type { CSSProperties } from 'react';
import { useState } from 'react';

import { useList } from '../hooks/useApi';

export interface ProductOption {
  id: number;
  name: string;
  code?: string;
  sku?: string | null;
  [field: string]: unknown;
}

interface Props {
  value?: number | null;
  /** Label for the current value when it is not in the loaded options (e.g. editing). */
  valueLabel?: string;
  onPick?: (product: ProductOption | null) => void;
  endpoint?: string;
  disabled?: boolean;
  allowClear?: boolean;
  placeholder?: string;
  style?: CSSProperties;
}

/** Server-side searchable product picker (searches name or code; active products only). */
export default function ProductSelect({
  value,
  valueLabel,
  onPick,
  endpoint = '/master/products',
  disabled,
  allowClear,
  placeholder = 'Search product',
  style,
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const list = useList<ProductOption>(endpoint, { search, page_size: 20, is_active: true }, open);
  const products = list.data?.items ?? [];

  const label = (p: ProductOption) => {
    const code = p.code ?? p.sku;
    return code ? `${code} ${p.name}` : p.name;
  };
  const options = products.map((p) => ({ value: p.id, label: label(p) }));
  // Keep the current product visible even when it is not in the search results.
  if (value && !options.some((o) => o.value === value)) {
    options.unshift({ value, label: valueLabel ?? `#${value}` });
  }

  return (
    <Select
      showSearch={{ filterOption: false, onSearch: setSearch }}
      value={value ?? undefined}
      placeholder={placeholder}
      options={options}
      loading={list.isFetching}
      disabled={disabled}
      allowClear={allowClear}
      onOpenChange={setOpen}
      notFoundContent={list.isError ? 'Could not load products' : list.isFetching ? 'Loading…' : 'No products'}
      style={{ width: '100%', minWidth: 220, ...style }}
      onChange={(id?: number) => onPick?.(id ? (products.find((p) => p.id === id) ?? null) : null)}
    />
  );
}
