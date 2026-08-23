import { useEffect, useRef, useState } from 'react';

export interface FilterField {
  key: string;
  label: string;
  type: 'search' | 'select';
  options?: { value: string; label: string }[];
  placeholder?: string;
}

interface Props {
  fields: FilterField[];
  values: Record<string, string>;
  total: number;
  onChange: (key: string, value: string) => void;
}

/** 筛选栏：搜索框 + 下拉 + 右侧总数。搜索输入做 300ms 防抖。 */
export default function FilterBar({ fields, values, total, onChange }: Props) {
  const [draft, setDraft] = useState<Record<string, string>>(values);
  const prevValues = useRef(values);
  /** 本组件通过 onChange 推上去的值，回流时不再覆盖 draft。 */
  const pushed = useRef<Record<string, string>>({});

  // 只同步真正被外部改动的键：整体 setDraft(values) 会在切换下拉时
  // 把正在输入的搜索词一起重置掉。
  useEffect(() => {
    const prev = prevValues.current;
    prevValues.current = values;
    const changed = Object.keys(values).filter(
      (k) => values[k] !== prev[k] && values[k] !== pushed.current[k],
    );
    if (!changed.length) return;
    setDraft((d) => {
      const next = { ...d };
      changed.forEach((k) => (next[k] = values[k]));
      return next;
    });
  }, [values]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fields.forEach((f) => {
        if (f.type === 'search' && (draft[f.key] ?? '') !== (values[f.key] ?? '')) {
          pushed.current[f.key] = draft[f.key] ?? '';
          onChange(f.key, draft[f.key] ?? '');
        }
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [draft, fields, values, onChange]);

  return (
    <div className="filter-bar">
      {fields.map((f) => {
        const id = `filter-${f.key}`;
        return (
          <div key={f.key} className={`filter-field ${f.type}`}>
            <label htmlFor={id}>{f.label}</label>
            {f.type === 'search' ? (
              <input
                id={id}
                value={draft[f.key] ?? ''}
                placeholder={f.placeholder}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              />
            ) : (
              <select
                id={id}
                value={values[f.key] ?? ''}
                onChange={(e) => onChange(f.key, e.target.value)}
              >
                {f.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
          </div>
        );
      })}
      <div className="filter-total">共 {total.toLocaleString('zh-CN')} 条</div>
    </div>
  );
}
