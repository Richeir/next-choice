import { CollectionError } from './errors';

const SH_SEGMENTS = ['60', '68', '51', '52', '53', '55', '56', '58'];
const SZ_SEGMENTS = ['00', '30', '15', '16'];

/** 由 6 位纯数字 code 的号段推断市场（对齐 scripts/transform.py::market_of）。 */
export function marketOf(code: string): 'SH' | 'SZ' {
  const prefix = code.slice(0, 2);
  if (SH_SEGMENTS.includes(prefix)) return 'SH';
  if (SZ_SEGMENTS.includes(prefix)) return 'SZ';
  throw new CollectionError(`unknown code segment: ${code}`);
}

/** 600000 -> sh600000（新浪 K 线接口格式）。 */
export const toSinaCode = (code: string): string =>
  marketOf(code).toLowerCase() + code;

/** 600000 -> SH600000（雪球接口格式）。 */
export const toXqCode = (code: string): string => marketOf(code) + code;

/** sh600000 -> 600000。 */
export const stripPrefix = (prefixed: string): string => prefixed.slice(2);

/** 脏数据容忍的数值转换：null/空串/'-'/NaN/Infinity -> null。 */
export function numOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** 亿 -> 元；脏值透传 null。 */
export const yiToYuan = (v: unknown): number | null => {
  const n = numOrNull(v);
  return n === null ? null : n * 1e8;
};

/** 万 -> 元；脏值透传 null。 */
export const wanToYuan = (v: unknown): number | null => {
  const n = numOrNull(v);
  return n === null ? null : n * 1e4;
};
