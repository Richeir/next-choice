export function Loading({ text = '加载中…' }: { text?: string }) {
  return <div className="state-view">{text}</div>;
}

export function ErrorView({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-view error">
      <div>{message}</div>
      {onRetry && (
        <div className="retry">
          <button className="btn" onClick={onRetry}>
            重试
          </button>
        </div>
      )}
    </div>
  );
}

export function Empty({ text = '暂无数据' }: { text?: string }) {
  return <div className="state-view">{text}</div>;
}
