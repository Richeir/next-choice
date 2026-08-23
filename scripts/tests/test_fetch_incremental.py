"""fetch_data 增量逻辑单元测试：频率门控 _due_freqs + 增量起始日回退。"""
from datetime import date

import pandas as pd
import pytest

import db
import fetch_data
from conftest import SCHEMA

COLS = fetch_data.src.KLINE_COLS


def _df(rows):
    return pd.DataFrame(rows, columns=COLS)


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
        # 入库起点对齐到前一周周一 2023-12-25；实际抓取起点再向前扩展
        # 取窗口首行的 preclose 上下文（2023-12-25 - 12 天 = 2023-12-13）
        assert seen["start"] == "2023-12-13"


class TestOverlapPreclose:
    """增量/重叠重拉不得把重叠区已入库的 preclose/pctChg 覆盖成 NULL。"""

    def test_daily_overlap_keeps_preclose(self, tmp_path, monkeypatch):
        conn = db.init_db(str(tmp_path / "t.db"), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        # 存量：01-04 / 01-05 已有正确的 preclose
        conn.execute("INSERT INTO stock_kline_daily (date, code, close,"
                     " preclose, pctChg, adjustflag) VALUES"
                     " ('2024-01-04','600000',10.0,9.5,5.26,'3'),"
                     " ('2024-01-05','600000',10.5,10.0,5.0,'3')")
        conn.commit()
        # 增量重拉返回 01-04 起的数据（窗口从 01-04 开始，其首行在
        # shift 逻辑下 preclose 为 NaN）
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: _df([
            ("2024-01-04", 10, 10, 10, 10.0, float("nan"), 100, 1e3,
             None, float("nan")),
            ("2024-01-05", 10, 11, 10, 10.5, 10.0, 100, 1e3, None, 5.0),
            ("2024-01-08", 10.5, 11, 10, 11.0, 10.5, 100, 1e3, None, 4.76),
        ]))
        fetch_data.fetch_stock_kline(conn, ["daily"], ["3"], "2024-01-01",
                                     "2024-01-31", incremental=True,
                                     today="2024-01-08", sleep_s=0)
        row = conn.execute("SELECT preclose, pctChg FROM stock_kline_daily"
                           " WHERE date='2024-01-04'").fetchone()
        # 重叠区 01-04 的正确值保留，未被窗口首行的 NaN 覆盖
        assert row["preclose"] == 9.5
        assert row["pctChg"] == 5.26
        # 新行 01-08 正常入库
        assert conn.execute("SELECT count(*) c FROM stock_kline_daily"
                            ).fetchone()["c"] == 3

    def test_weekly_partial_bar_no_null_overwrite(self, tmp_path, monkeypatch):
        """周线增量：前一周完整周 K 的 pctChg 不被打空（窗口扩展提供上下文）。"""
        conn = db.init_db(str(tmp_path / "t.db"), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        # 存量完整周：12-25 ~ 12-29 所在周
        conn.execute("INSERT INTO stock_kline_weekly (date, code, close,"
                     " pctChg, adjustflag) VALUES"
                     " ('2023-12-29','600000',10.0,2.5,'3')")
        conn.commit()

        def fake(code, start, end, adjust="", max_retries=3):
            return _df([
                ("2023-12-25", 9.5, 10, 9, 9.8, 9.4, 100, 1e3, None, 4.25),
                ("2023-12-26", 9.8, 10, 9.5, 9.9, 9.8, 100, 1e3, None, 1.02),
                ("2023-12-27", 9.9, 10, 9.7, 9.95, 9.9, 100, 1e3, None, 0.50),
                ("2023-12-28", 9.95, 10, 9.8, 10.0, 9.95, 100, 1e3, None,
                 0.50),
                ("2023-12-29", 10.0, 10, 9.9, 10.0, 10.0, 100, 1e3, None,
                 0.0),
                ("2024-01-02", 10.0, 10.5, 10, 10.2, 10.0, 100, 1e3, None,
                 2.0),
                ("2024-01-03", 10.2, 10.5, 10.1, 10.4, 10.2, 100, 1e3, None,
                 1.96),
            ])
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        fetch_data.fetch_stock_kline(conn, ["weekly"], ["3"], "2023-11-01",
                                     "2024-01-31", incremental=True,
                                     today="2024-01-06", sleep_s=0)  # 周六
        rows = {r["date"]: r for r in conn.execute(
            "SELECT * FROM stock_kline_weekly").fetchall()}
        # 前一周（12-25 所在周）：扩展窗口内的重采样得到正确
        # preclose/pctChg，不再被首行 NaN 打空
        assert rows["2023-12-29"]["pctChg"] is not None
        # 进行中周（01-02/01-03）以最后交易日入库
        assert "2024-01-03" in rows

    def test_partial_period_stale_rows_replaced(self, tmp_path, monkeypatch):
        """进行中周期二次抓取：旧的半成品行被清理，不堆积重复周。"""
        conn = db.init_db(str(tmp_path / "t.db"), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        # 周三抓的半成品周行（date=周三）
        conn.execute("INSERT INTO stock_kline_weekly (date, code, close,"
                     " adjustflag) VALUES ('2024-01-03','600000',10.2,'3')")
        conn.commit()

        def fake(code, start, end, adjust="", max_retries=3):
            return _df([
                ("2024-01-02", 10.0, 10.5, 10, 10.2, 10.0, 100, 1e3, None,
                 2.0),
                ("2024-01-03", 10.2, 10.5, 10.1, 10.4, 10.2, 100, 1e3, None,
                 1.96),
                ("2024-01-04", 10.4, 10.6, 10.3, 10.5, 10.4, 100, 1e3, None,
                 0.96),
                ("2024-01-05", 10.5, 10.8, 10.4, 10.7, 10.5, 100, 1e3, None,
                 1.90),
            ])
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        fetch_data.fetch_stock_kline(conn, ["weekly"], ["3"], "2023-11-01",
                                     "2024-01-31", incremental=True,
                                     today="2024-01-06", sleep_s=0)
        rows = conn.execute("SELECT date, close FROM stock_kline_weekly"
                            " ORDER BY date").fetchall()
        # 该周只剩一根（周五的完整版本），半成品行被删除而非并存
        assert [(r["date"], r["close"]) for r in rows] == \
            [("2024-01-05", 10.7)]


class TestSingleFetchPerAdjust:
    """周/月由日线本地派生，多频率不得对同一 code 重复请求日 K。"""

    def _seed(self, tmp_path, name="t.db"):
        conn = db.init_db(str(tmp_path / name), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        conn.commit()
        return conn

    def _daily(self):
        return _df([
            ("2024-01-02", 10.0, 10.5, 10, 10.2, 10.0, 100, 1e3, None, 2.0),
            ("2024-01-03", 10.2, 10.5, 10.1, 10.4, 10.2, 100, 1e3, None, 1.96),
            ("2024-01-04", 10.4, 10.6, 10.3, 10.5, 10.4, 100, 1e3, None, 0.96),
            ("2024-01-05", 10.5, 10.8, 10.4, 10.7, 10.5, 100, 1e3, None, 1.90),
        ])

    def test_three_freqs_one_request_per_adjust(self, tmp_path, monkeypatch):
        conn = self._seed(tmp_path)
        calls = []

        def fake(code, start, end, adjust="", max_retries=3):
            calls.append((code, adjust, start))
            return self._daily()
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)

        fetch_data.fetch_stock_kline(
            conn, ["daily", "weekly", "monthly"], ["2", "3"],
            "2024-01-01", "2024-01-31", today="2024-01-08", sleep_s=0)

        # 3 频率 × 2 复权原本要 6 次请求，现在每档复权只抓一次日线
        assert len(calls) == 2
        assert sorted(c[1] for c in calls) == ["", "qfq"]
        # 三张表都写到了
        for table in ("stock_kline_daily", "stock_kline_weekly",
                      "stock_kline_monthly"):
            n = conn.execute(f"SELECT count(*) c FROM {table}").fetchone()["c"]
            assert n > 0, table

    def test_derived_rows_match_per_freq_fetch(self, tmp_path, monkeypatch):
        """派生结果与逐频率单独抓取一致。"""
        conn = self._seed(tmp_path)
        monkeypatch.setattr(fetch_data.src, "stock_kline",
                            lambda *a, **kw: self._daily())
        fetch_data.fetch_stock_kline(conn, ["daily", "weekly", "monthly"],
                                     ["3"], "2024-01-01", "2024-01-31",
                                     today="2024-01-08", sleep_s=0)
        combined = {
            t: conn.execute(f"SELECT date, open, high, low, close, volume"
                            f" FROM {t} ORDER BY date").fetchall()
            for t in ("stock_kline_daily", "stock_kline_weekly",
                      "stock_kline_monthly")}

        conn2 = self._seed(tmp_path, "separate.db")
        for freq in ("daily", "weekly", "monthly"):
            fetch_data.fetch_stock_kline(conn2, [freq], ["3"], "2024-01-01",
                                         "2024-01-31", force=True,
                                         today="2024-01-08", sleep_s=0)
        for table, rows in combined.items():
            other = conn2.execute(
                f"SELECT date, open, high, low, close, volume FROM {table}"
                " ORDER BY date").fetchall()
            assert [tuple(r) for r in rows] == [tuple(r) for r in other], table


class TestQfqIncrementalFullRefresh:
    """前复权增量必须全量重刷（复权基准在除权后整体平移，增量会混用基准）。"""

    def test_qfq_refetches_from_start(self, tmp_path, monkeypatch):
        conn = db.init_db(str(tmp_path / "t.db"), SCHEMA)
        conn.execute("INSERT INTO stock_info (code, code_name, market, type,"
                     " status) VALUES ('600000','浦发银行','SH','1','1')")
        conn.execute("INSERT INTO stock_kline_daily (date, code, close,"
                     " adjustflag) VALUES ('2024-01-05','600000',10.5,'3')")
        conn.commit()
        seen = {}

        def fake(code, start, end, adjust="", max_retries=3):
            seen[adjust] = start
            return pd.DataFrame(columns=COLS)
        monkeypatch.setattr(fetch_data.src, "stock_kline", fake)
        fetch_data.fetch_stock_kline(conn, ["daily"], ["2", "3"],
                                     "2020-01-01", "2024-01-31",
                                     incremental=True, today="2024-01-08",
                                     sleep_s=0)
        # 不复权：增量起点 2024-01-04，再向前扩展 8 天取上下文
        assert seen[""] == "2023-12-27"
        # 前复权：从全量起点 --start 重刷（不增量）
        assert seen["qfq"] == "2020-01-01"


class TestPadStart:
    def test_pad_does_not_cross_full_start(self):
        # 增量起点已接近全量起点时，扩展不越过全量起点
        assert fetch_data._pad_start("daily", "2020-01-03",
                                     "2020-01-01") == "2020-01-01"

    def test_pad_weekly(self):
        assert fetch_data._pad_start("weekly", "2023-12-25",
                                     "2020-01-01") == "2023-12-13"

    def test_pad_monthly(self):
        assert fetch_data._pad_start("monthly", "2023-12-01",
                                     "2020-01-01") == "2023-10-22"
