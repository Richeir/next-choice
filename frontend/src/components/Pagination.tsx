import { fmtInt } from '../utils/format';

interface Props {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
}

export default function Pagination({ page, pageSize, total, onPageChange, onPageSizeChange }: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div className="pagination">
      <div className="info">
        <span>
          第 {page} / {totalPages} 页 · 显示 {from} – {to} · 共 {fmtInt(total)} 条
        </span>
        {onPageSizeChange && (
          <>
            <span>|</span>
            <span>每页</span>
            <select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
              {[20, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <span>条</span>
          </>
        )}
      </div>
      <div className="page-btns">
        <button className="btn" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          上一页
        </button>
        <button
          className="btn primary"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
