"""fetch_data.update_stock_list + build_parser 单元测试：mock 掉 BaoStock，验证基础信息写入行为与 CLI 解析。"""
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


# query_daily_history_k_AStock 字段（与 query_daily_history_k_ETF 一致）。
_ASTOCK_FIELDS = [
    "date", "code", "open", "high", "low", "close", "preclose",
    "volume", "amount", "adjustflag", "turn", "tradestatus",
    "pctChg", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "isST",
]


def _astock_list_rs(codes):
    """构造 AStock 列表返回值：仅取 code 字段。"""
    rows = [["2026-02-04", c] + [""] * (len(_ASTOCK_FIELDS) - 2) for c in codes]
    return _FakeRS(rows=rows, fields=_ASTOCK_FIELDS)


def _basic_rs(code, name, ipo="2000-01-01", outDate="", stype="1", status="1"):
    return _FakeRS(rows=[[code, name, ipo, outDate, stype, status]])


@pytest.fixture()
def conn(tmp_path):
    return db.init_db(str(tmp_path / "test.db"), SCHEMA)


class TestUpdateStockList:
    def test_writes_basic_info_for_each_code(self, conn, monkeypatch):
        codes = ["sh.600000", "sz.000001", "sh.688981"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_AStock",
            lambda date="": _astock_list_rs(codes),
        )
        monkeypatch.setattr(
            fetch_data.bs, "query_stock_basic",
            lambda code="": _basic_rs(code, name=f"股票-{code.split('.')[1]}"),
        )

        n_ok, n_fail = fetch_data.update_stock_list(conn, "2026-02-04")

        assert n_ok == 3
        assert n_fail == 0
        rows = conn.execute(
            "SELECT code, code_name, market, type FROM stock_info ORDER BY code"
        ).fetchall()
        assert [(r["code"], r["code_name"], r["market"], r["type"]) for r in rows] == [
            ("sh.600000", "股票-600000", "SH", "1"),
            ("sh.688981", "股票-688981", "SH", "1"),
            ("sz.000001", "股票-000001", "SZ", "1"),
        ]

    def test_dedups_codes_before_querying_basic(self, conn, monkeypatch):
        # AStock 接口理论不会重复，但防御性去重（与 ETF 模式一致）。
        basic_calls = []
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_AStock",
            lambda date="": _astock_list_rs(["sh.600000", "sh.600000", "sh.600000"]),
        )
        def _stub_basic(code=""):
            basic_calls.append(code)
            return _basic_rs(code, "浦发银行")
        monkeypatch.setattr(fetch_data.bs, "query_stock_basic", _stub_basic)

        n_ok, _ = fetch_data.update_stock_list(conn, "2026-02-04")

        assert n_ok == 1
        assert basic_calls == ["sh.600000"]
        assert conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0] == 1

    def test_single_failure_warns_and_continues(self, conn, monkeypatch, caplog):
        codes = ["sh.600000", "sz.000001", "sh.688981"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_AStock",
            lambda date="": _astock_list_rs(codes),
        )
        def _stub_basic(code=""):
            if code == "sh.600000":
                return _FakeRS(error_code="10010001", error_msg="network timeout")
            return _basic_rs(code, "测试" + code.split(".")[1])
        monkeypatch.setattr(fetch_data.bs, "query_stock_basic", _stub_basic)

        with caplog.at_level(logging.WARNING):
            n_ok, n_fail = fetch_data.update_stock_list(conn, "2026-02-04")

        assert n_ok == 2
        assert n_fail == 1
        assert conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0] == 2
        assert any("sh.600000" in r.getMessage() for r in caplog.records)

    def test_skips_non_stock_basic_type(self, conn, monkeypatch):
        """防御：万一 AStock 返回中带 ETF（理论上不会），basic 拿到 type='5' 时跳过。"""
        codes = ["sh.600000", "sh.510010"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_AStock",
            lambda date="": _astock_list_rs(codes),
        )
        def _stub_basic(code=""):
            # sh.510010 类型为 '5' (ETF)，应被跳过
            stype = "5" if code == "sh.510010" else "1"
            return _basic_rs(code, "异类", stype=stype)
        monkeypatch.setattr(fetch_data.bs, "query_stock_basic", _stub_basic)

        n_ok, n_fail = fetch_data.update_stock_list(conn, "2026-02-04")

        assert n_ok == 1
        assert n_fail == 1
        rows = conn.execute("SELECT code FROM stock_info").fetchall()
        assert [r["code"] for r in rows] == ["sh.600000"]
        # ETF 不能进 stock_info
        assert conn.execute("SELECT COUNT(*) FROM etf_info").fetchone()[0] == 0

    def test_list_query_failure_raises(self, conn, monkeypatch):
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_AStock",
            lambda date="": _FakeRS(error_code="10010001", error_msg="network fail"),
        )

        with pytest.raises(RuntimeError, match="query_daily_history_k_AStock"):
            fetch_data.update_stock_list(conn, "2026-02-04")

    def test_idempotent_replace_on_rerun(self, conn, monkeypatch):
        codes = ["sh.600000"]
        monkeypatch.setattr(
            fetch_data.bs, "query_daily_history_k_AStock",
            lambda date="": _astock_list_rs(codes),
        )
        monkeypatch.setattr(
            fetch_data.bs, "query_stock_basic",
            lambda code="": _basic_rs(code, "浦发银行"),
        )

        fetch_data.update_stock_list(conn, "2026-02-04")
        first = conn.execute(
            "SELECT code_name FROM stock_info WHERE code='sh.600000'"
        ).fetchone()["code_name"]
        assert first == "浦发银行"

        # 二次跑（mock 返回新名字）→ OR REPLACE 应更新同一行
        monkeypatch.setattr(
            fetch_data.bs, "query_stock_basic",
            lambda code="": _basic_rs(code, "改名后"),
        )
        fetch_data.update_stock_list(conn, "2026-02-04")

        second = conn.execute(
            "SELECT code_name FROM stock_info WHERE code='sh.600000'"
        ).fetchone()["code_name"]
        assert second == "改名后"
        assert conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0] == 1


class TestBuildParser:
    """CLI 解析验证：--update-etf-list / --update-stock-list 与 --codes 三者互斥。"""

    def test_stock_list_flag_sets_true(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--update-stock-list"])
        assert ns.codes is None
        assert ns.update_etf_list is False
        assert ns.update_stock_list is True
        assert ns.list_date is None

    def test_stock_list_with_list_date(self):
        parser = fetch_data.build_parser()
        ns = parser.parse_args(["--update-stock-list", "--list-date", "2025-08-15"])
        assert ns.update_stock_list is True
        assert ns.list_date == "2025-08-15"

    def test_stock_list_and_codes_mutually_exclusive(self):
        parser = fetch_data.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--update-stock-list", "--codes", "sh.600000"])

    def test_etf_list_and_stock_list_mutually_exclusive(self):
        parser = fetch_data.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--update-etf-list", "--update-stock-list"])
