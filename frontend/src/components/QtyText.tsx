import { formatDecimal } from '../utils/decimal';
import type { Decimalish } from '../utils/decimal';

interface Props {
  value: Decimalish;
  unit?: string;
}

/** Quantity (up to 3 decimals, trailing zeros trimmed), right-aligned. */
export default function QtyText({ value, unit }: Props) {
  const text = formatDecimal(value, 3, true);
  return (
    <span style={{ display: 'block', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
      {text || '—'}
      {text && unit ? ` ${unit}` : ''}
    </span>
  );
}
