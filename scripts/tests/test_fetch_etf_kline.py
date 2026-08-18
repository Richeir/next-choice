"""fetch_data.fetch_etf_kline + CLI 解析单元测试：mock 掉 BaoStock，验证
从 etf_info 表全量读代码、按 日/周/月 × 复权 抓 K 线入库的行为。

与 --update-etf-list 不同，本命令不重新查询列表接口，只依赖 etf_info 表。
"""
import logging

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
    """构造一行与 etf_{freq} 表字段数匹配的返回行。"""
    freq = _FREQ_BACK[frequency]
    fields = fetch_data._kline_fields("etf", freq).split(",")
    row = [""] * len(fields)
    row[0] = start
    row[1] = code
    row[fields.index("adjustflag")] = adjustflag
    return _FakeRS(rows=[row])


def _seed_etf_info(conn, codes):
    for i, c in enumerate(codes, 1):
        conn.execute(
            "INSERT INTO etf_info (code, code_name, market, type) VALUES (?,?,?,?)",
            (c, f"基金-{i}", c.split(".")[0].upper(), "5"),
        )
    conn.commit()


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestFetchEtfKline:
    def test_fetches_all_freqs_and_adjusts(self, conn, monkeypatch):
        codes = ["sh.510010", "sz.159915"]
        _seed_etf_info(conn, codes)

        calls = []

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            calls.append((code, frequency, adjustflag))
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_etf_kline(
            conn, ["daily", "weekly", "monthly"], ["2", "3"],
            "2026-01-05", "2026-12-31",
        )

        assert n_ok == 2
        assert n_fail == 0
        # 2 codes × 3 freq × 2 adjust
        assert len(calls) == 2 * 3 * 2
        # 每种复权都覆盖到（前复权 '2' 与 不复权 '3'，符合 db-design 策略）
        assert set(a for _, _, a in calls) == {"2", "3"}
        # 每张表 = 2 codes × 2 adjusts(2,3)
        for table in ["etf_kline_daily", "etf_kline_weekly", "etf_kline_monthly"]:
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 2 * 2

    def test_empty_etf_info_is_noop(self, conn, monkeypatch):
        calls = []

        def _fake(**kwargs):
            calls.append(kwargs)
            return _FakeRS(rows=[])

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        n_ok, n_fail = fetch_data.fetch_etf_kline(
            conn, ["daily"], ["2", "3"], "2026-01-05", "2026-12-31",
        )

        assert n_ok == 0
        assert n_fail == 0
        assert calls == []

    def test_single_failure_warns_and_continues(self, conn, monkeypatch, caplog):
        codes = ["sh.510010", "sz.159915"]
        _seed_etf_info(conn, codes)

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            if code == "sh.510010":
                return _FakeRS(error_code="10010001", error_msg="network timeout")
            return _kline_rs(code, frequency, adjustflag, start_date)

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        with caplog.at_level(logging.WARNING):
            n_ok, n_fail = fetch_data.fetch_etf_kline(
                conn, ["daily"], ["3"], "2026-01-05", "2026-12-31",
            )

        assert n_ok == 1  # sz.159915 成功
        assert n_fail == 1  # sh.510010 失败
        assert any("sh.510010" in r.getMessage() for r in caplog.records)
        assert conn.execute("SELECT COUNT(*) FROM etf_kline_daily").fetchone()[0] == 1

    def test_backfills_etf_info(self, conn, monkeypatch):
        # 回填依赖不复权('3')日 K 的最大日期行写入 last_trade_date/last_close/last_pct_chg
        _seed_etf_info(conn, ["sh.510010"])

        def _fake(code="", fields="", start_date="", end_date="",
                  frequency="", adjustflag=""):
            if frequency == "d" and adjustflag == "3":
                # 日 K 不复权返回带收盘价/涨跌幅的一行
                flds = fetch_data._kline_fields("etf", "daily").split(",")
                row = [""] * len(flds)
                row[0], row[1] = start_date, code
                row[flds.index("adjustflag")] = adjustflag
                row[flds.index("close")] = "3.50"
                row[flds.index("pctChg")] = "1.23"
                return _FakeRS(rows=[row])
            return _FakeRS(rows=[])

        monkeypatch.setattr(fetch_data.bs, "query_history_k_data_plus", _fake)

        fetch_data.fetch_etf_kline(
            conn, ["daily"], ["3"], "2026-01-05", "2026-12-31",
        )

        info = conn.execute(
            "SELECT last_trade_date, last_close, last_pct_chg FROM etf_info "
            "WHERE code='sh.510010'"
        ).fetchone()
        assert info["last_trade_date"] == "2026-01-05"
        assert info["last_close"] == 3.5
        assert info["last_pct_chg"] == 1.23


class TestBuildParser:
    """--fetch-etf-kline 选项解析：互斥组识别、默认复权 2,3。"""

    def test_fetch_etf_kline_flag_parsed(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--fetch-etf-kline"])
        assert ns.fetch_etf_kline is True
        assert ns.codes is None
        assert ns.update_etf_list is False
        assert ns.update_stock_list is False

    def test_default_adjust_is_23_for_fetch_etf_kline(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--fetch-etf-kline"])
        assert ns.adjust is None  # 由 main 在 fetch_etf_kline 分支默认成 "2,3"
