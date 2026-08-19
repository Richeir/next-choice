"""fetch_data 增量模式（--incremental）单元测试：mock 掉 BaoStock，验证

- 起始日期取 DB 中该证券该频率的 MAX(date)（重拉最后一天覆盖修正）；
- 频率门控：daily 仅周一~周五；weekly 周六/周日 或 最后一根周 K 距今 >7 天；
  monthly 月初前 3 天 或 最后一根月 K 距今 >31 天（无数据的新证券不门控）；
- last_fetch_date==今天 跳过；应更频率全部成功才标记。
"""
from datetime import date

import pytest

import db
import fetch_data
from conftest import SCHEMA

_FREQ_BACK = {"d": "daily", "w": "weekly", "m": "monthly"}


class _FakeRS:
    """模拟 baostock 的 ResultData：next/get_row_data + error_code/msg。"""

    def __init__(self, rows=None, error_code="0", error_msg=""):
        self._rows = list(rows or [])
        self._iter = iter(self._rows)
        self.error_code = error_code
        self.error_msg = error_msg

    def next(self):
        try:
            self._current = next(self._iter)
            return True
        except StopIteration:
            return False

    def get_row_data(self):
        return self._current


def _kline_rs(code, frequency, adjustflag, start):
    """构造一行与 stock_{freq} 表字段数匹配的返回行。"""
    freq = _FREQ_BACK[frequency]
    fields = fetch_data._kline_fields("stock", freq).split(",")
    row = [""] * len(fields)
    row[0] = start
    row[1] = code
    row[fields.index("adjustflag")] = adjustflag
    return _FakeRS(rows=[row])


def _seed_stock_info(conn, codes):
    for i, c in enumerate(codes, 1):
        conn.execute(
            "INSERT INTO stock_info (code, code_name, market, type) VALUES (?,?,?,?)",
            (c, f"股票-{i}", c.split(".")[0].upper(), "1"),
        )
    conn.commit()


def _seed_kline(conn, kind, freq, code, dates, adjustflag="3"):
    """向 K 线表写入指定日期的最小行（其余字段空串 -> NULL）。"""
    fields = fetch_data._kline_fields(kind, freq).split(",")
    rows = []
    for d in dates:
        row = [""] * len(fields)
        row[0] = d
        row[1] = code
        row[fields.index("adjustflag")] = adjustflag
        rows.append(row)
    db.insert_kline(conn, kind, freq, adjustflag, rows)


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestDueFreqs:
    """_due_freqs 频率门控纯逻辑（today: date；last: {freq: 'YYYY-MM-DD' 或 None}）。"""

    # --- daily：周一~周五更新；周末不更新（有数据时）；无数据不门控 ---

    def test_daily_due_on_weekday(self):
        today = date(2026, 8, 18)  # 周二
        assert fetch_data._due_freqs(["daily"], today, {"daily": "2026-08-17"}) == ["daily"]

    def test_daily_not_due_on_weekend(self):
        assert fetch_data._due_freqs(["daily"], date(2026, 8, 22), {"daily": "2026-08-21"}) == []  # 周六
        assert fetch_data._due_freqs(["daily"], date(2026, 8, 23), {"daily": "2026-08-21"}) == []  # 周日

    def test_daily_due_on_weekend_without_data(self):
        # 新证券补全不受周末门控
        assert fetch_data._due_freqs(["daily"], date(2026, 8, 22), {"daily": None}) == ["daily"]

    # --- weekly：周六/周日，或最后一根周 K 距今 >7 天 ---

    def test_weekly_due_on_saturday(self):
        # 周六：最新周 K 尚未入库（最后一根是上周，距今 >2 天）
        today = date(2026, 8, 22)  # 周六，last=上周五 8/14，距今 8 天
        assert fetch_data._due_freqs(["weekly"], today, {"weekly": "2026-08-14"}) == ["weekly"]

    def test_weekly_due_on_sunday(self):
        today = date(2026, 8, 23)  # 周日，last=上周五 8/14，距今 9 天
        assert fetch_data._due_freqs(["weekly"], today, {"weekly": "2026-08-14"}) == ["weekly"]

    def test_weekly_not_due_on_weekend_when_fresh(self):
        # 周六已入库最新周 K（距今 ≤2 天）：周六/周日都不再重抓，避免冗余请求
        assert fetch_data._due_freqs(["weekly"], date(2026, 8, 22), {"weekly": "2026-08-21"}) == []  # 周六 gap=1
        assert fetch_data._due_freqs(["weekly"], date(2026, 8, 23), {"weekly": "2026-08-21"}) == []  # 周日 gap=2

    def test_weekly_weekend_boundary_2_days(self):
        # 周末 gap 恰好 2 天 -> 不更新（要求 >2）；gap 3 天 -> 更新（周六未抓到时周日重试）
        assert fetch_data._due_freqs(["weekly"], date(2026, 8, 23), {"weekly": "2026-08-21"}) == []
        assert fetch_data._due_freqs(["weekly"], date(2026, 8, 23), {"weekly": "2026-08-20"}) == ["weekly"]

    def test_weekly_not_due_on_weekday_with_fresh_data(self):
        today = date(2026, 8, 18)  # 周二，最后周 K 距今 4 天
        assert fetch_data._due_freqs(["weekly"], today, {"weekly": "2026-08-14"}) == []

    def test_weekly_due_on_weekday_when_stale(self):
        today = date(2026, 8, 18)  # 周二，最后周 K 距今 8 天 > 7
        assert fetch_data._due_freqs(["weekly"], today, {"weekly": "2026-08-10"}) == ["weekly"]

    def test_weekly_boundary_7_days_not_due(self):
        today = date(2026, 8, 18)  # 距今恰好 7 天 -> 不更新（要求 >7）
        assert fetch_data._due_freqs(["weekly"], today, {"weekly": "2026-08-11"}) == []

    def test_weekly_due_without_data(self):
        assert fetch_data._due_freqs(["weekly"], date(2026, 8, 18), {"weekly": None}) == ["weekly"]

    # --- monthly：月初前 3 天，或最后一根月 K 距今 >31 天 ---

    def test_monthly_due_in_first_3_days(self):
        assert fetch_data._due_freqs(["monthly"], date(2026, 9, 1), {"monthly": "2026-08-31"}) == ["monthly"]
        assert fetch_data._due_freqs(["monthly"], date(2026, 9, 3), {"monthly": "2026-08-31"}) == ["monthly"]

    def test_monthly_not_due_mid_month_with_fresh_data(self):
        today = date(2026, 9, 4)  # day=4，最后月 K 距今 4 天
        assert fetch_data._due_freqs(["monthly"], today, {"monthly": "2026-08-31"}) == []

    def test_monthly_due_mid_month_when_stale(self):
        today = date(2026, 9, 4)  # 最后月 K 距今 35 天 > 31
        assert fetch_data._due_freqs(["monthly"], today, {"monthly": "2026-07-31"}) == ["monthly"]

    def test_monthly_boundary_31_days_not_due(self):
        today = date(2026, 9, 4)  # 距今恰好 31 天 -> 不更新（要求 >31）
        assert fetch_data._due_freqs(["monthly"], today, {"monthly": "2026-08-04"}) == []

    def test_monthly_due_without_data(self):
        assert fetch_data._due_freqs(["monthly"], date(2026, 9, 4), {"monthly": None}) == ["monthly"]

    # --- 组合 ---

    def test_mixed_freqs_partial_due(self):
        today = date(2026, 8, 22)  # 周六：daily 门控跳过，weekly 未入库更新
        due = fetch_data._due_freqs(
            ["daily", "weekly", "monthly"], today,
            {"daily": "2026-08-21", "weekly": "2026-08-14", "monthly": "2026-07-31"},
        )
        assert due == ["weekly"]


class TestDelistedSkip:
    """增量模式跳过退市证券（status='0'），避免对其周期性空查。"""

    @pytest.fixture()
    def conn(self, tmp_path):
        return db.init_db(str(tmp_path / "test.db"), SCHEMA)

    def test_delisted_code_skipped_in_incremental(self, conn, monkeypatch):
        _seed_stock_info(conn, ["sh.600000", "sh.600001"])
        conn.execute("UPDATE stock_info SET status='0' WHERE code='sh.600001'")
        conn.commit()
        # 退市证券数据停在 2020 年：若不跳过会触发 daily/weekly/monthly 补漏请求
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-17"])
        _seed_kline(conn, "stock", "daily", "sh.600001", ["2020-06-30"])
        _seed_kline(conn, "stock", "weekly", "sh.600001", ["2020-06-30"])
        _seed_kline(conn, "stock", "monthly", "sh.600001", ["2020-06-30"])

        calls = []

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            calls.append(code)
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily", "weekly", "monthly"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,
        )

        assert (n_ok, n_fail) == (1, 0)
        assert set(calls) == {"sh.600000"}  # 退市证券未发任何请求
        assert conn.execute(
            "SELECT last_fetch_date FROM stock_info WHERE code='sh.600001'"
        ).fetchone()["last_fetch_date"] is None

    def test_full_mode_ignores_delisted_status(self, conn, monkeypatch):
        # 全量模式不跳过退市证券（保持原行为，供历史补全）
        _seed_stock_info(conn, ["sh.600001"])
        conn.execute("UPDATE stock_info SET status='0' WHERE code='sh.600001'")
        conn.commit()

        calls = []

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            calls.append(code)
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18",
        )

        assert calls == ["sh.600001"]


class TestKlineMaxDate:
    """db.kline_max_date：每张 K 线表一次性聚合出每只证券的最后日期。"""

    def test_returns_max_date_per_code(self, conn):
        _seed_kline(conn, "stock", "weekly", "sh.600000", ["2026-08-10", "2026-08-17"])
        _seed_kline(conn, "stock", "weekly", "sz.000001", ["2026-08-14"])
        assert db.kline_max_date(conn, "stock", "weekly") == {
            "sh.600000": "2026-08-17",
            "sz.000001": "2026-08-14",
        }

    def test_ignores_other_freq_table(self, conn):
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-21"])
        assert db.kline_max_date(conn, "stock", "weekly") == {}

    def test_empty_table_returns_empty_dict(self, conn):
        assert db.kline_max_date(conn, "etf", "monthly") == {}


class TestIncrementalFetch:
    """fetch_stock_kline(..., incremental=True) 端到端行为（mock BaoStock）。"""

    def test_start_date_is_db_max_date(self, conn, monkeypatch):
        # 已有日 K 到 2026-08-17；今天周二 -> daily 应更，起始日 = 2026-08-17
        _seed_stock_info(conn, ["sh.600000"])
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-14", "2026-08-17"])

        calls = []

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            calls.append((code, frequency, start_date, end_date))
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["2", "3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,
        )

        assert (n_ok, n_fail) == (1, 0)
        assert len(calls) == 2  # daily × 复权 2,3
        assert all(s == "2026-08-17" for _, _, s, _ in calls)  # 从最后日期重拉
        assert all(e == "2026-08-18" for _, _, _, e in calls)

    def test_new_code_falls_back_to_start(self, conn, monkeypatch):
        # 表里无数据的新证券：用 --start 回退，且不做频率门控
        _seed_stock_info(conn, ["sh.688001"])

        calls = []

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            calls.append((frequency, start_date))
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily", "weekly", "monthly"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,
        )

        assert (n_ok, n_fail) == (1, 0)
        assert {f for f, _ in calls} == {"d", "w", "m"}
        assert all(s == "2021-01-01" for _, s in calls)

    def test_weekend_skips_daily_fetches_weekly(self, conn, monkeypatch):
        # 周六：daily 有数据被门控跳过；weekly 未入库（距今 8 天）更新
        _seed_stock_info(conn, ["sh.600000"])
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-21"])
        _seed_kline(conn, "stock", "weekly", "sh.600000", ["2026-08-14"])
        _seed_kline(conn, "stock", "monthly", "sh.600000", ["2026-07-31"])

        calls = []

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            calls.append(frequency)
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily", "weekly", "monthly"], ["3"], "2021-01-01", "2026-08-22",
            today="2026-08-22", incremental=True,  # 周六
        )

        assert (n_ok, n_fail) == (1, 0)
        assert calls == ["w"]  # 只抓周 K

    def test_sunday_skips_fresh_weekly(self, conn, monkeypatch):
        # 周日：周六已入库最新周 K（距今 2 天）且 daily 周末不开盘 -> 无请求
        _seed_stock_info(conn, ["sh.600000"])
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-21"])
        _seed_kline(conn, "stock", "weekly", "sh.600000", ["2026-08-21"])
        _seed_kline(conn, "stock", "monthly", "sh.600000", ["2026-07-31"])

        calls = []

        def _fake(*a, **kw):
            calls.append(kw)
            return _FakeRS(rows=[])

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily", "weekly", "monthly"], ["3"], "2021-01-01", "2026-08-23",
            today="2026-08-23", incremental=True,  # 周日
        )

        assert (n_ok, n_fail) == (0, 0)
        assert calls == []

    def test_nothing_due_skips_without_mark(self, conn, monkeypatch):
        # 工作日只请求周/月 K 且都新鲜（未过门控阈值）-> 全部跳过、不标记
        _seed_stock_info(conn, ["sh.600000"])
        _seed_kline(conn, "stock", "weekly", "sh.600000", ["2026-08-14"])  # 距今 4 天
        _seed_kline(conn, "stock", "monthly", "sh.600000", ["2026-07-31"])  # 距今 18 天

        calls = []

        def _fake(*a, **kw):
            calls.append(kw)
            return _FakeRS(rows=[])

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["weekly", "monthly"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,  # 周二
        )

        assert (n_ok, n_fail) == (0, 0)
        assert calls == []
        assert conn.execute(
            "SELECT last_fetch_date FROM stock_info WHERE code='sh.600000'"
        ).fetchone()["last_fetch_date"] is None

    def test_marks_fetched_when_due_freqs_succeed(self, conn, monkeypatch):
        # 增量模式下：应更频率（哪怕只有 daily）全部成功即标记 last_fetch_date
        _seed_stock_info(conn, ["sh.600000"])
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-17"])

        monkeypatch.setattr(
            fetch_data.bs, "query_history_k_data_plus",
            lambda code="", fields="", start_date="", end_date="",
                   frequency="", adjustflag="": _kline_rs(code, frequency, adjustflag, start_date),
        )

        fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,
        )

        assert conn.execute(
            "SELECT last_fetch_date FROM stock_info WHERE code='sh.600000'"
        ).fetchone()["last_fetch_date"] == "2026-08-18"

    def test_skips_fetched_today(self, conn, monkeypatch):
        # 今天已标记的证券直接跳过（断点续传/防重跑）
        _seed_stock_info(conn, ["sh.600000"])
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-17"])
        conn.execute(
            "UPDATE stock_info SET last_fetch_date='2026-08-18' WHERE code='sh.600000'")
        conn.commit()

        calls = []

        def _fake(*a, **kw):
            calls.append(kw)
            return _FakeRS(rows=[])

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,
        )

        assert (n_ok, n_fail) == (0, 0)
        assert calls == []

    def test_failure_not_marked_for_retry(self, conn, monkeypatch):
        # 增量模式失败的证券不标记，重跑可继续
        _seed_stock_info(conn, ["sh.600000", "sz.000001"])
        _seed_kline(conn, "stock", "daily", "sh.600000", ["2026-08-17"])
        _seed_kline(conn, "stock", "daily", "sz.000001", ["2026-08-17"])

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            if code == "sh.600000":
                return _FakeRS(error_code="10010001", error_msg="network timeout")
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_stock_kline(
            conn, ["daily"], ["3"], "2021-01-01", "2026-08-18",
            today="2026-08-18", incremental=True,
        )

        assert (n_ok, n_fail) == (1, 1)
        assert conn.execute(
            "SELECT last_fetch_date FROM stock_info WHERE code='sh.600000'"
        ).fetchone()["last_fetch_date"] is None
        assert conn.execute(
            "SELECT last_fetch_date FROM stock_info WHERE code='sz.000001'"
        ).fetchone()["last_fetch_date"] == "2026-08-18"


class TestIncrementalParser:
    """--incremental 选项解析。"""

    def test_incremental_flag_parsed(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--fetch-stock-kline", "--incremental"])
        assert ns.incremental is True

    def test_incremental_default_false(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--fetch-stock-kline"])
        assert ns.incremental is False

    def test_incremental_with_codes_rejected(self):
        parser = fetch_data.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--codes", "sh.600000", "--incremental"])

    def test_incremental_with_update_list_rejected(self):
        parser = fetch_data.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--update-stock-list", "--incremental"])
