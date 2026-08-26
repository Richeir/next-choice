import { FetchLike } from '../http';

export interface MockRoute {
  /** 返回 true 则命中该路由。 */
  match: (url: string) => boolean;
  /** 响应体；string 直接返回，object 序列化为 JSON。 */
  body: string | object;
  status?: number;
  headers?: Record<string, string | string[]>;
}

/**
 * 构造可注入的 fetch mock：按注册顺序取第一个命中的路由；
 * 未命中时抛错并附上请求 URL，避免测试静默走真实网络。
 */
export function makeMockFetch(routes: readonly MockRoute[]): FetchLike & {
  calls: string[];
} {
  const calls: string[] = [];
  const impl = (async (url: string) => {
    calls.push(url);
    const route = routes.find((r) => r.match(url));
    if (!route) {
      throw new Error(`mock fetch: no route for ${url}`);
    }
    // 先取值再判型：body 可能是计数用 getter，只允许触发一次
    const rawBody = route.body;
    const body = typeof rawBody === 'string' ? rawBody : JSON.stringify(rawBody);
    const headers = new Headers();
    for (const [name, value] of Object.entries(route.headers ?? {})) {
      // set-cookie 可能多值，需逐条 append
      if (Array.isArray(value)) value.forEach((v) => headers.append(name, v));
      else headers.append(name, value);
    }
    return new Response(body, { status: route.status ?? 200, headers });
  }) as FetchLike & { calls: string[] };
  impl.calls = calls;
  return impl;
}

/** 从仓库 fixture 文件读文本（spec 与 fixtures 同目录树下）。 */
export function readFixture(relativePath: string): string {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { readFileSync } = require('fs') as typeof import('fs');
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { join } = require('path') as typeof import('path');
  return readFileSync(join(__dirname, '..', 'fixtures', relativePath), 'latin1');
}
