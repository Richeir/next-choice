import { Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import HomePage from './pages/HomePage';
import StocksPage from './pages/StocksPage';
import EtfsPage from './pages/EtfsPage';
import DetailPage from './pages/DetailPage';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/stocks" element={<StocksPage />} />
        <Route path="/etfs" element={<EtfsPage />} />
        <Route path="/stocks/:code" element={<DetailPage kind="stock" />} />
        <Route path="/etfs/:code" element={<DetailPage kind="etf" />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </Layout>
  );
}
