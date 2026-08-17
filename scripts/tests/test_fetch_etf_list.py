"""fetch_data.update_etf_list + build_parser 单元测试：mock 掉 BaoStock，验证基础信息写入行为与 CLI 解析。"""
import logging

import pytest

import db
import fetch_data
from conftest import SCHEMA


class _FakeRS:
    """模拟 baostock 的 ResultData：next/get_row_data/fields + error_code/msg。"""

    def __init__(self, rows=None, fields=None, error_code="0", error_msg=""):
        self._rows = list(rows or [])
        self._iter = iter(self._rows)
        self.fields = fields or []
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


_ETF_LIST_FIELDS = [
    "date", "code", "open", "high", "low", "close", "preclose",
    "volume", "amount", "adjustflag", "turn", "tradestatus",
    "pctChg", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "isST",
]


def _etf_list_rs(codes):
    rows = [["2026-02-04", c] + [""] * (len(_ETF_LIST_FIELDS) - 2) for c in codes]
    return _FakeRS(rows=rows, fields=_ETF_LIST_FIELDS)


def _basic_rs(code, name, ipo="2020-01-01", outDate="", stype="5", status="1"):
    return _FakeRS(rows=[[code, name, ipo, outDate, stype, status]])


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestUpdateEtfList:
    def test_writes_basic_info_for_each_code(self, conn, monkeypatch):
        codes = ["sh.510010", "sz.159915"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_ETF",
            lambda date="": _etf_list_rs(codes),
        )
        monkeypatch.setattr(
            fetch_data.bs, "query_stock_basic",
            lambda code="": _basic_rs(code, name=f"基金-{code.split('.')[1]}"),
        )

        n_ok, n_fail = fetch_data.update_etf_list(conn, "2026-02-04")

        assert n_ok == 2
        assert n_fail == 0
        rows = conn.execute(
            "SELECT code, code_name, market, type FROM etf_info ORDER BY code"
        ).fetchall()
        assert [(r["code"], r["code_name"], r["market"], r["type"]) for r in rows] == [
            ("sh.510010", "基金-510010", "SH", "5"),
            ("sz.159915", "基金-159915", "SZ", "5"),
        ]

    def test_dedups_codes_before_querying_basic(self, conn, monkeypatch):
        # query_daily_history_k_ETF 可能重复返回同一 code（数据问题/重采样），应去重后只查一次
        basic_calls = []
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_ETF",
            lambda date="": _etf_list_rs(["sh.510010", "sh.510010", "sh.510010"]),
        )
        def _stub_basic(code=""):
            basic_calls.append(code)
            return _basic_rs(code, "上证50ETF")
        monkeypatch.setattr(fetch_data.bs, "query_stock_basic", _stub_basic)

        n_ok, _ = fetch_data.update_etf_list(conn, "2026-02-04")

        assert n_ok == 1
        assert basic_calls == ["sh.510010"]
        assert conn.execute("SELECT COUNT(*) FROM etf_info").fetchone()[0] == 1

    def test_single_failure_warns_and_continues(self, conn, monkeypatch, caplog):
        codes = ["sh.510010", "sz.159915"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_ETF",
            lambda date="": _etf_list_rs(codes),
        )
        def _stub_basic(code=""):
            if code == "sh.510010":
                return _FakeRS(error_code="10010001", error_msg="network timeout")
            return _basic_rs(code, "创业板ETF")
        monkeypatch.setattr(fetch_data.bs, "query_stock_basic", _stub_basic)

        with caplog.at_level(logging.WARNING):
            n_ok, n_fail = fetch_data.update_etf_list(conn, "2026-02-04")

        assert n_ok == 1
        assert n_fail == 1
        assert conn.execute("SELECT COUNT(*) FROM etf_info").fetchone()[0] == 1
        assert any("sh.510010" in r.getMessage() for r in caplog.records)

    def test_list_query_failure_raises(self, conn, monkeypatch):
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_ETF",
            lambda date="": _FakeRS(error_code="10010001", error_msg="network fail"),
        )

        with pytest.raises(RuntimeError, match="query_daily_history_k_ETF"):
            fetch_data.update_etf_list(conn, "2026-02-04")

    def test_idempotent_replace_on_rerun(self, conn, monkeypatch):
        codes = ["sh.510010"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_ETF",
            lambda date="": _etf_list_rs(codes),
        )
        monkeypatch.setattr(
            fetch_data.bs, "query_stock_basic",
            lambda code="": _basic_rs(code, "上证50ETF"),
        )

        fetch_data.update_etf_list(conn, "2026-02-04")
        first = conn.execute(
            "SELECT code_name FROM etf_info WHERE code='sh.510010'"
        ).fetchone()["code_name"]
        assert first == "上证50ETF"

        # 二次跑（mock 返回新名字）→ OR REPLACE 应更新同一行
        monkeypatch.setattr(
            fetch_data.bs, "query_stock_basic",
            lambda code="": _basic_rs(code, "改名后ETF"),
        )
        fetch_data.update_etf_list(conn, "2026-02-04")

        second = conn.execute(
            "SELECT code_name FROM etf_info WHERE code='sh.510010'"
        ).fetchone()["code_name"]
        assert second == "改名后ETF"
        assert conn.execute("SELECT COUNT(*) FROM etf_info").fetchone()[0] == 1


class TestBuildParser:
    """CLI 解析验证：--codes 可选；--update-etf-list 与 --codes 互斥；--list-date 可识别。"""

    def test_codes_optional(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--update-etf-list"])
        assert ns.codes is None
        assert ns.update_etf_list is True
        assert ns.list_date is None

    def test_list_date_parsed(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(
            ["--codes", "sh.600000", "--list-date", "2025-08-15"]
        )
        assert ns.list_date == "2025-08-15"
        assert ns.update_etf_list is False