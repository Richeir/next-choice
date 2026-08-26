/**
 * TS 采集模块（issue #55 步骤 2）：Python scripts/akshare_source.py 的平移。
 * 纯库实现，不感知 SQLite 与 Nest —— A1（CLI）/A2（Nest cron）路线决策
 * （步骤 3）落地前保持两侧皆可挂载。
 */

export * from './errors';
export * from './http';
export * from './codes';
export * from './normalize';
export * from './resample';
export { decodeSinaKlines, HK_JS_DECODE } from './sina-decrypt';
export type { DecodedBar } from './sina-decrypt';
export * from './sources/sina-kline';
export * from './sources/tencent-stock-list';
export * from './sources/sina-etf-list';
export * from './sources/sina-fund-scale';
export * from './sources/ths-etf-category';
export * from './sources/xueqiu';
