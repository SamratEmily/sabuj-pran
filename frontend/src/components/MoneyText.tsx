import type { CSSProperties } from 'react';

import { compare, formatDecimal } from '../utils/decimal';
import type { Decimalish } from '../utils/decimal';

interface Props {
  value: Decimalish;
  /** Decimal places (2 for money, 4 for unit costs). */
  scale?: number;
  /** Colour negatives red. */
  signed?: boolean;
  strong?: boolean;
  style?: CSSProperties;
}

/** Money with 2 decimals (or `scale`), right-aligned, tabular digits. Empty values render as "—". */
export default function MoneyText({ value, scale = 2, signed, strong, style }: Props) {
  const text = formatDecimal(value, scale);
  const negative = signed && text !== '' && compare(value, 0) < 0;
  return (
    <span
      style={{
        display: 'block',
        textAlign: 'right',
        fontVariantNumeric: 'tabular-nums',
        fontWeight: strong ? 600 : undefined,
        color: negative ? 'var(--ant-color-error, #ff4d4f)' : undefined,
        ...style,
      }}
    >
      {text || '—'}
    </span>
  );
}
