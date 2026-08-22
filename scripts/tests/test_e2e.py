"""真实网络端到端冒烟（默认跳过：-m e2e 显式运行）。"""
import pytest

import akshare_source as src


@pytest.mark.e2e
def test_stock_kline_real():
    df = src.stock_kline("600000", "2024-01-02", "2024-01-05")
    assert df is not None and len(df) > 0


@pytest.mark.e2e
def test_etf_kline_real():
    df = src.etf_kline("510050", "2024-01-02", "2024-01-05")
    assert df is not None and len(df) > 0
