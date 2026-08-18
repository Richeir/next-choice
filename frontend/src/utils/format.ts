/** 数字格式化工具 */

const nf = (digits = 2) =>
  new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

/** 千分位数字，如 5,348 / 1,654.00 */
export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return nf(digits).format(v);
}

/** 整数千分位，如 5,348 */
export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return nf(0).format(v);
}

/** 涨跌幅：+2.45% / -0.42% */
export function fmtPct(v: number | null | undefined, withSign = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const sign = withSign && v > 0 ? '+' : '';
  return `${sign}${nf(2).format(v)}%`;
}

/** 金额（元）→ 亿 / 万亿，如 48.1 亿、1,832 亿、2.60 万亿 */
export function fmtAmountYi(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const yi = v / 1e8;
  const f1 = new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: 1,
  });
  if (Math.abs(yi) >= 1e4) return `${nf(2).format(yi / 1e4)} 万亿`;
  if (Math.abs(yi) >= 1) return `${f1.format(yi)} 亿`;
  return `${f1.format(v / 1e4)} 万`;
}

/** 涨跌方向 class：涨=up(绿) 跌=down(红)，以设计图为准 */
export function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return '';
  return v > 0 ? 'up' : 'down';
}

/** 证券代码 sh.600000 → 600000（展示用） */
export function shortCode(code: string): string {
  return code.includes('.') ? code.split('.')[1] : code;
}

/** sh.600000 → 600000.SH（详情页头部） */
export function displayCode(code: string): string {
  const [ex, num] = code.split('.');
  return num && ex ? `${num}.${ex.toUpperCase()}` : code;
}

/** 简单移动平均 */
export function movingAverage(values: number[], window: number): (number | null)[] {
  return values.map((_, i) => {
    if (i < window - 1) return null;
    let sum = 0;
    for (let j = i - window + 1; j <= i; j++) sum += values[j];
    return sum / window;
  });
}
