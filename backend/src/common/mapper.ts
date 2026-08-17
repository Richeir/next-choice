/** snake_case → camelCase 映射工具。 */

export function toCamel(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase());
}

/** 将一行数据库结果（snake_case 列名）映射为 camelCase 对象。 */
export function rowToCamel(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    out[toCamel(k)] = v === undefined ? null : v;
  }
  return out;
}
