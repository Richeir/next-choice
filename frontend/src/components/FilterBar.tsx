import { useEffect, useState } from 'react';

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

  useEffect(() => {
    setDraft(values);
  }, [values]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fields.forEach((f) => {
        if (f.type === 'search' && (draft[f.key] ?? '') !== (values[f.key] ?? '')) {
          onChange(f.key, draft[f.key] ?? '');
        }
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [draft, fields, values, onChange]);

  return (
    <div className="filter-bar">
      {fields.map((f) => (
        <div key={f.key} className={`filter-field ${f.type}`}>
          <label>{f.label}</label>
          {f.type === 'search' ? (
            <input
              value={draft[f.key] ?? ''}
              placeholder={f.placeholder}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            />
          ) : (
            <select
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
      ))}
      <div className="filter-total">共 {total.toLocaleString('zh-CN')} 条</div>
    </div>
  );
}
