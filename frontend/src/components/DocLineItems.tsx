import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, InputNumber, Table, Tooltip, Typography } from 'antd';
import type { TableProps } from 'antd';
import type { ReactNode } from 'react';

import { useStockOf } from '../api/inventory';
import { compare, multiply, sum } from '../utils/decimal';
import MoneyText from './MoneyText';
import ProductSelect from './ProductSelect';
import type { ProductOption } from './ProductSelect';
import QtyText from './QtyText';

export type { ProductOption } from './ProductSelect';

/** One editable document line. Quantities and prices are decimal strings; documents may
 *  carry extra per-line fields (direction, system_qty, ...). */
export interface DocLine {
  key: string;
  product_id?: number;
  product_name?: string;
  qty?: string | null;
  price?: string | null;
  [field: string]: unknown;
}

/** A document-specific column, inserted after Product (default) or after Qty. */
export interface ExtraLineColumn {
  key: string;
  title: ReactNode;
  width?: number;
  afterQty?: boolean;
  render: (line: DocLine, update: (patch: Partial<DocLine>) => void) => ReactNode;
}

interface Props {
  /** Controlled value; works directly inside <Form.Item name="lines">. */
  value?: DocLine[];
  onChange?: (lines: DocLine[]) => void;
  /** Show price, amount and the total row (default true). Stock documents turn it off. */
  showPrice?: boolean;
  priceLabel?: string;
  /** Decimal places for the price: 2 for selling prices, 4 for unit costs. */
  priceScale?: 2 | 4;
  qtyLabel?: string;
  /** Show an "Available" column for this warehouse and flag lines asking for more. */
  availableIn?: number | null;
  extraColumns?: ExtraLineColumn[];
  productEndpoint?: string;
  /** Price to prefill when a product is picked (default: the product's current_price). */
  defaultPrice?: (product: ProductOption) => string | null | undefined;
  /** Default fields for a newly added line. */
  newLineDefaults?: Partial<DocLine>;
  disabled?: boolean;
}

let lineCounter = 0;
export function newLine(partial: Partial<DocLine> = {}): DocLine {
  lineCounter += 1;
  return { key: `line-${Date.now()}-${lineCounter}`, qty: '1', price: null, ...partial };
}

export function lineAmount(line: DocLine): string {
  return multiply(line.qty, line.price, 2);
}

export function linesTotal(lines: DocLine[] | undefined): string {
  return sum((lines ?? []).map(lineAmount), 2);
}

function checkProductsAndQty(lines: DocLine[] | undefined, allowZero = false): void {
  if (!lines?.length) throw new Error('Add at least one line');
  const seen = new Set<number>();
  lines.forEach((line, i) => {
    const row = `Line ${i + 1}`;
    if (!line.product_id) throw new Error(`${row}: choose a product`);
    if (seen.has(line.product_id)) throw new Error(`${row}: ${line.product_name ?? 'this product'} is already on another line`);
    seen.add(line.product_id);
    const bad = allowZero ? compare(line.qty, 0) < 0 : compare(line.qty, 0) <= 0;
    if (!line.qty || bad) throw new Error(`${row}: quantity must be ${allowZero ? '0 or more' : 'more than 0'}`);
  });
}

/** Form.Item validator: at least one line, each with product, qty > 0 and price >= 0. */
export async function validateLines(_: unknown, lines: DocLine[] | undefined): Promise<void> {
  checkProductsAndQty(lines);
  lines!.forEach((line, i) => {
    if (line.price === null || line.price === undefined || line.price === '' || compare(line.price, 0) < 0)
      throw new Error(`Line ${i + 1}: enter a price`);
  });
}

/** Form.Item validator for documents without prices (stock documents). */
export async function validateQtyLines(_: unknown, lines: DocLine[] | undefined): Promise<void> {
  checkProductsAndQty(lines);
}

/** Like validateQtyLines but 0 is allowed (physical count: counted nothing). */
export async function validateCountLines(_: unknown, lines: DocLine[] | undefined): Promise<void> {
  checkProductsAndQty(lines, true);
}

function AvailableCell({ line, warehouseId }: { line: DocLine; warehouseId: number }) {
  const stock = useStockOf(line.product_id, warehouseId);
  if (!line.product_id) return null;
  if (stock.isPending) return <Typography.Text type="secondary">…</Typography.Text>;
  const available = stock.data?.qty_available ?? '0';
  const short = compare(line.qty, available) > 0;
  return (
    <Tooltip title={short ? 'More than is available in this warehouse' : undefined}>
      <span style={{ color: short ? 'var(--ant-color-error, #ff4d4f)' : undefined, fontWeight: short ? 600 : undefined }}>
        <QtyText value={available} unit={stock.data?.unit_code} />
      </span>
    </Tooltip>
  );
}

const right = (text: ReactNode) => <span style={{ display: 'block', textAlign: 'right' }}>{text}</span>;

export default function DocLineItems({
  value = [],
  onChange,
  showPrice = true,
  priceLabel = 'Unit price',
  priceScale = 2,
  qtyLabel = 'Qty',
  availableIn,
  extraColumns = [],
  productEndpoint = '/master/products',
  defaultPrice,
  newLineDefaults,
  disabled,
}: Props) {
  const update = (key: string, patch: Partial<DocLine>) =>
    onChange?.(value.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const remove = (key: string) => onChange?.(value.filter((l) => l.key !== key));
  const add = () => onChange?.([...value, newLine({ ...(showPrice ? {} : { price: undefined }), ...newLineDefaults })]);

  const toColumn = (c: ExtraLineColumn) => ({
    title: c.title,
    key: c.key,
    width: c.width,
    render: (_: unknown, line: DocLine) => c.render(line, (patch: Partial<DocLine>) => update(line.key, patch)),
  });

  const columns: TableProps<DocLine>['columns'] = [
    { title: '#', key: 'n', width: 48, render: (_, __, i) => i + 1 },
    {
      title: 'Product',
      key: 'product',
      render: (_, line) => (
        <ProductSelect
          endpoint={productEndpoint}
          value={line.product_id}
          valueLabel={line.product_name}
          disabled={disabled}
          onPick={(p) =>
            p &&
            update(line.key, {
              product_id: p.id,
              product_name: p.code ? `${p.code} ${p.name}` : p.name,
              ...(showPrice
                ? { price: line.price ?? (defaultPrice ? defaultPrice(p) : (p.current_price as string | null | undefined)) ?? null }
                : {}),
            })
          }
        />
      ),
    },
    ...(availableIn
      ? [{ title: right('Available'), key: 'available', width: 130, render: (_: unknown, line: DocLine) => <AvailableCell line={line} warehouseId={availableIn} /> }]
      : []),
    ...extraColumns.filter((c) => !c.afterQty).map(toColumn),
    {
      title: qtyLabel,
      key: 'qty',
      width: 140,
      render: (_, line) => (
        <InputNumber<string>
          stringMode
          min="0"
          precision={3}
          value={line.qty ?? null}
          disabled={disabled}
          onChange={(qty) => update(line.key, { qty })}
          style={{ width: '100%' }}
          aria-label={qtyLabel}
        />
      ),
    },
    ...extraColumns.filter((c) => c.afterQty).map(toColumn),
    ...(showPrice
      ? [
          {
            title: priceLabel,
            key: 'price',
            width: 160,
            render: (_: unknown, line: DocLine) => (
              <InputNumber<string>
                stringMode
                min="0"
                precision={priceScale}
                value={line.price ?? null}
                disabled={disabled}
                onChange={(price) => update(line.key, { price })}
                style={{ width: '100%' }}
                aria-label={priceLabel}
              />
            ),
          },
          {
            title: right('Amount'),
            key: 'amount',
            width: 150,
            render: (_: unknown, line: DocLine) => <MoneyText value={lineAmount(line)} />,
          },
        ]
      : []),
    {
      key: 'remove',
      width: 48,
      render: (_, line) => (
        <Button
          type="text"
          danger
          icon={<DeleteOutlined />}
          aria-label="Remove line"
          disabled={disabled}
          onClick={() => remove(line.key)}
        />
      ),
    },
  ];
  const lastIndex = columns.length - 1;

  return (
    <Table<DocLine>
      rowKey="key"
      size="small"
      columns={columns}
      dataSource={value}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: 'No lines yet' }}
      footer={() => (
        <Button type="dashed" icon={<PlusOutlined />} onClick={add} disabled={disabled} block>
          Add line
        </Button>
      )}
      summary={
        showPrice
          ? () => (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={lastIndex - 1} align="right">
                  <Typography.Text strong>Total</Typography.Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={lastIndex - 1}>
                  <MoneyText value={linesTotal(value)} strong />
                </Table.Summary.Cell>
                <Table.Summary.Cell index={lastIndex} />
              </Table.Summary.Row>
            )
          : undefined
      }
    />
  );
}
