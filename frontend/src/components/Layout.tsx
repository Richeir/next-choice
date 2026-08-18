import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, Link } from 'react-router-dom';
import { BANNER_TEXT, FALLBACK_DATA_DATE } from '../config';
import { getStocks } from '../api';

function useDataDate(): string {
  const [date, setDate] = useState<string>(FALLBACK_DATA_DATE);
  useEffect(() => {
    let alive = true;
    getStocks({ page: 1, pageSize: 1, sortBy: 'lastTradeDate', order: 'desc' })
      .then((res) => {
        if (alive) {
          const d = res.items[0]?.lastTradeDate;
          if (d) setDate(d);
        }
      })
      .catch(() => {
        /* 取不到时保留兜底值 */
      });
    return () => {
      alive = false;
    };
  }, []);
  return date;
}

export default function Layout({ children }: { children: ReactNode }) {
  const dataDate = useDataDate();
  return (
    <div className="app-shell">
      <div className="banner">{BANNER_TEXT}</div>
      <header className="navbar">
        <div className="container navbar-inner">
          <Link to="/" className="brand">
            <span className="brand-logo">M</span>
            <span>M·STOCK</span>
          </Link>
          <nav className="nav-links">
            <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              首页
            </NavLink>
            <NavLink
              to="/stocks"
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
            >
              股票
            </NavLink>
            <NavLink
              to="/etfs"
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
            >
              ETF
            </NavLink>
          </nav>
          <div className="data-date">
            <span className="dot" />
            <span>数据日期</span>
            <span className="mono">{dataDate}</span>
          </div>
        </div>
      </header>
      <main className="app-main">
        <div className="container">{children}</div>
      </main>
      <footer className="footer">
        <div className="container footer-inner">
          <span>© 2026 M·STOCK · 数据来自示例源,仅供原型演示</span>
          <span className="footer-links">
            <Link to="/">首页</Link>
            <Link to="/stocks">股票</Link>
            <Link to="/etfs">ETF</Link>
            <a href="#">使用文档</a>
            <a href="#">隐私</a>
          </span>
        </div>
      </footer>
    </div>
  );
}
