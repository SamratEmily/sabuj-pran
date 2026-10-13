/**
 * Exact decimal helpers for API decimal strings. Never converts money/qty to floats:
 * values are handled as scaled BigInts (e.g. "12.34" at scale 2 -> 1234n).
 */

export type Decimalish = string | number | null | undefined;

const WORK_SCALE = 6; // enough for qty (3) and unit cost (4)

const pow10 = (n: number): bigint => 10n ** BigInt(n);

/** Parse to a BigInt scaled by `scale`, rounding half away from zero. null if not a number. */
export function parseDecimal(value: Decimalish, scale: number): bigint | null {
  if (value === null || value === undefined) return null;
  const match = /^([+-])?(\d*)(?:\.(\d*))?$/.exec(String(value).trim());
  if (!match || (match[2] === '' && !match[3])) return null;
  const negative = match[1] === '-';
  const fraction = match[3] ?? '';
  let scaled = BigInt(match[2] || '0') * pow10(scale) + BigInt(fraction.slice(0, scale).padEnd(scale, '0') || '0');
  if (fraction.length > scale && fraction[scale] >= '5') scaled += 1n;
  return negative ? -scaled : scaled;
}

function rescale(value: bigint, from: number, to: number): bigint {
  if (to >= from) return value * pow10(to - from);
  const divisor = pow10(from - to);
  const half = divisor / 2n;
  return value >= 0n ? (value + half) / divisor : -((-value + half) / divisor);
}

/** Plain decimal string ("-1234.50") from a scaled BigInt. */
export function toDecimalString(value: bigint, scale: number): string {
  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(scale + 1, '0');
  const int = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale);
  return `${negative ? '-' : ''}${int}${scale ? `.${fraction}` : ''}`;
}

/** a * b rounded to `scale` places, as a string. Empty inputs count as 0. */
export function multiply(a: Decimalish, b: Decimalish, scale = 2): string {
  const x = parseDecimal(a, WORK_SCALE) ?? 0n;
  const y = parseDecimal(b, WORK_SCALE) ?? 0n;
  return toDecimalString(rescale(x * y, WORK_SCALE * 2, scale), scale);
}

/** Sum rounded to `scale` places, as a string. Empty inputs count as 0. */
export function sum(values: Decimalish[], scale = 2): string {
  const total = values.reduce<bigint>((acc, v) => acc + (parseDecimal(v, WORK_SCALE) ?? 0n), 0n);
  return toDecimalString(rescale(total, WORK_SCALE, scale), scale);
}

/** a - b rounded to `scale` places, as a string. Empty inputs count as 0. */
export function subtract(a: Decimalish, b: Decimalish, scale = 2): string {
  const x = parseDecimal(a, WORK_SCALE) ?? 0n;
  const y = parseDecimal(b, WORK_SCALE) ?? 0n;
  return toDecimalString(rescale(x - y, WORK_SCALE, scale), scale);
}

/** Compare two decimals: -1, 0 or 1. */
export function compare(a: Decimalish, b: Decimalish): number {
  const x = parseDecimal(a, WORK_SCALE) ?? 0n;
  const y = parseDecimal(b, WORK_SCALE) ?? 0n;
  return x === y ? 0 : x < y ? -1 : 1;
}

/** "1234567.5" -> "1,234,567.50". Returns '' for empty input. */
export function formatDecimal(value: Decimalish, scale: number, trimZeros = false): string {
  const parsed = parseDecimal(value, scale);
  if (parsed === null) return '';
  let text = toDecimalString(parsed, scale);
  if (trimZeros && text.includes('.')) text = text.replace(/\.?0+$/, '');
  const [int, fraction] = text.split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return fraction !== undefined ? `${grouped}.${fraction}` : grouped;
}
