"""fetch_data 增量逻辑单元测试：频率门控 _due_freqs + 增量起始日回退。"""
from datetime import date

import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA


class TestDueFreqs:
    def test_new_security_all_freqs(self):
        assert fetch_data._due_freqs(
            ["daily", "weekly", "monthly"], date(2024, 1, 3),
            {"daily": None, "weekly": None, "monthly": None}
        ) == ["daily", "weekly", "monthly"]

    def test_daily_only_weekday(self):
        assert fetch_data._due_freqs(["daily"], date(2024, 1, 6),  # 周六
                                     {"daily": "2024-01-05"}) == []
        assert fetch_data._due_freqs(["daily"], date(2024, 1, 8),  # 周一
                                     {"daily": "2024-01-05"}) == ["daily"]

    def test_weekly_weekend_gate(self):
        # 周六，最后周 K 距今 3 天 -> 到期
        assert fetch_data._due_freqs(["weekly"], date(2024, 1, 6),
                                     {"weekly": "2024-01-03"}) == ["weekly"]
        # 周六，最后周 K 就是昨天 -> 不门控（已抓过本周）
        assert fetch_data._due_freqs(["weekly"], date(2024, 1, 6),
                                     {"weekly": "2024-01-05"}) == []
        # 工作日但距今超 7 天（补漏）
        assert fetch_data._due_freqs(["weekly"], date(2024, 1, 15),
                                     {"weekly": "2024-01-03"}) == ["weekly"]

    def test_monthly_gate(self):
        assert fetch_data._due_freqs(["monthly"], date(2024, 1, 2),
                                     {"monthly": "2023-12-29"}) == ["monthly"]
        assert fetch_data._due_freqs(["monthly"], date(2024, 1, 15),
                                     {"monthly": "2023-12-29"}) == []
        assert fetch_data._due_freqs(["monthly"], date(2024, 2, 15),
                                     {"monthly": "2023-12-29"}) == ["monthly"]


class TestIncFstart:
    def test_none_falls_back(self):
        assert fetch_data._inc_fstart("weekly", None, "2020-01-01") == "2020-01-01"

    def test_daily_back_one_day(self):
        assert fetch_data._inc_fstart("daily", "2024-01-05", "") == "2024-01-04"

    def test_weekly_aligns_to_prev_monday(self):
        # 2024-01-05 周五，所在周截止周日 01-07；回退到前一周周一 2023-12-25
        assert fetch_data._inc_fstart("weekly", "2024-01-05", "") == "2023-12-25"
        # base 本身就是周一也一样回退一整周，保证所在周完整
        assert fetch_data._inc_fstart("weekly", "2024-01-08", "") == "2024-01-01"

    def test_monthly_aligns_to_prev_month_first(self):
        assert fetch_data._inc_fstart("monthly", "2024-01-31", "") == "2023-12-01"
        assert fetch_data._inc_fstart("monthly", "2024-03-01", "") == "2024-02-01"


class TestIncrementalStart:
    def test_starts_from_last_date_aligned(self, tmp_path, monkeypatch):
        conn = db.init_db(str(tmp_path / "t.db"), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        # 注意：增量起始日取自该频率的 K 线表（这里必须插周 K 表）
        conn.execute("INSERT INTO stock_kline_weekly (date, code, close,"
                     " adjustflag) VALUES ('2024-01-05','600000',10.5,'3')")
        conn.commit()
        seen = {}

        def fake(code, start, end, adjust="", max_retries=3):
            seen["start"] = start
            return pd.DataFrame(columns=fetch_data.src.KLINE_COLS)
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        fetch_data.fetch_stock_kline(conn, ["weekly"], ["3"], "2020-01-01",
                                     "2024-01-31", incremental=True,
                                     today="2024-01-13", sleep_s=0)  # 周六
        # 最后周 K 2024-01-05（周五），起点对齐到前一周周一 2023-12-25，
        # 保证重采样不会用不完整周期覆盖已入库的完整周 K
        assert seen["start"] == "2023-12-25"
