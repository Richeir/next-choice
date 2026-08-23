import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div className="page">
      <div className="breadcrumb">— 系统数据</div>
      <h1 className="page-title">404 · 页面不存在</h1>
      <p className="page-desc">
        请检查链接是否正确，或从下面的入口重新进入。
      </p>
      <div className="notfound-links">
        <Link className="btn-view" to="/">
          返回首页
        </Link>
        <Link className="btn-view" to="/stocks">
          股票列表
        </Link>
        <Link className="btn-view" to="/etfs">
          ETF 列表
        </Link>
      </div>
    </div>
  );
}
