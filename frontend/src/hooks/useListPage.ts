import { useCallback, useEffect, useRef, useState } from 'react';
import type { ListParams, Paged } from '../api/types';

/** 列表页通用数据加载 hook：参数变化时重新请求，忽略过期响应 */
export function useListPage<T>(
  fetcher: (params: ListParams) => Promise<Paged<T>>,
  params: ListParams,
) {
  const [data, setData] = useState<Paged<T> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    fetcher(params)
      .then((res) => {
        if (id === seq.current) setData(res);
      })
      .catch((e: Error) => {
        if (id === seq.current) setError(e.message);
      })
      .finally(() => {
        if (id === seq.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(params)]);

  useEffect(load, [load]);

  return { data, loading, error, reload: load };
}
