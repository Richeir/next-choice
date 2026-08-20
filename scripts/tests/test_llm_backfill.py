"""llm_backfill 模块单元测试：缺失字段识别 / 校验 / 回填，不打网络。"""
import sqlite3

import pytest

import llm_backfill
from conftest import SCHEMA


def _conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    with open(SCHEMA, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def conn(tmp_path):
    return _conn(tmp_path)


describe = None


class TestValidate:
    def test_string_valid(self):
        assert llm_backfill._validate("industry", "银行") == "银行"
        assert llm_backfill._validate("fullName", " 某某股份有限公司 ") == "某某股份有限公司"

    def test_string_blank_or_too_long_rejected(self):
        assert llm_backfill._validate("industry", "") is None
        assert llm_backfill._validate("industry", "  ") is None
        assert llm_backfill._validate("industry", "x" * 101) is None

    def test_numeric_valid(self):
        assert llm_backfill._validate("pb", 1.2) == 1.2
        assert llm_backfill._validate("totalMarketCap", 10000) == 10000

    def test_numeric_negative_or_nonfinite_rejected(self):
        assert llm_backfill._validate("pb", -1) is None
        assert llm_backfill._validate("pb", float("nan")) is None
        assert llm_backfill._validate("pb", float("inf")) is None

    def test_high_low_52w_must_be_positive(self):
        assert llm_backfill._validate("high52w", 10) == 10
        assert llm_backfill._validate("high52w", 0) is None
        assert llm_backfill._validate("low52w", 0.5) == 0.5

    def test_wrong_type_rejected(self):
        assert llm_backfill._validate("industry", 123) is None
        assert llm_backfill._validate("pb", "1.2") is None
        assert llm_backfill._validate("pb", None) is None


class TestMissingTargets:
    def test_finds_missing_fields(self, conn):
        conn.execute(
            "INSERT INTO stock_info (code, industry) VALUES ('sh.600000', '银行')"
        )
        conn.execute(
            "INSERT INTO stock_info (code, industry, pb) VALUES ('sh.600001', '白酒', 2.5)"
        )
        targets = llm_backfill.missing_targets(conn, "stock")
        by_code = {t["code"]: t["missing"] for t in targets}
        assert "sh.600000" in by_code  # 部分字段为空
        assert "pb" in by_code["sh.600000"]
        assert "industry" not in by_code["sh.600000"]
        # sh.600001 已填 industry/pb，但其余 LLM 字段仍空，故仍命中但不含已填字段
        assert "sh.600001" in by_code
        assert "industry" not in by_code["sh.600001"]
        assert "pb" not in by_code["sh.600001"]

    def test_empty_string_treated_as_missing(self, conn):
        conn.execute(
            "INSERT INTO stock_info (code, industry) VALUES ('sh.600000', '')"
        )
        targets = llm_backfill.missing_targets(conn, "stock")
        assert "industry" in targets[0]["missing"]

    def test_codes_filter(self, conn):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600001')")
        targets = llm_backfill.missing_targets(conn, "stock", codes=["sh.600001"])
        assert len(targets) == 1
        assert targets[0]["code"] == "sh.600001"


class TestBackfillOne:
    def test_only_fills_empty_and_writes_timestamp(self, conn):
        conn.execute(
            "INSERT INTO stock_info (code, industry, pb) VALUES ('sh.600000', '银行', 1.2)"
        )
        target = {"code": "sh.600000", "code_name": "浦发银行", "missing": ["industry", "fullName"]}
        n = llm_backfill.backfill_one(conn, "stock", target, {
            "industry": "白酒",   # 已有值，忽略
            "pb": 3.5,            # 已有值，忽略
            "fullName": "某某股份有限公司",  # 空，回填
            "lastAmount": 9.9e8,
        })
        row = conn.execute("SELECT * FROM stock_info WHERE code='sh.600000'").fetchone()
        assert row["industry"] == "银行"
        assert row["pb"] == 1.2
        assert row["full_name"] == "某某股份有限公司"
        assert row["llm_backfill_at"]  # 时间戳已写
        assert n > 0

    def test_invalid_values_discarded(self, conn):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        target = {"code": "sh.600000", "code_name": "测试", "missing": ["industry", "pb", "high52w", "fullName"]}
        n = llm_backfill.backfill_one(conn, "stock", target, {
            "industry": "x" * 101,       # 超长，丢弃
            "pb": -2,                    # 负数，丢弃
            "high52w": 0,                # 52周高须为正，丢弃
            "fullName": "合法全称",       # 有效，回填
        })
        row = conn.execute("SELECT * FROM stock_info WHERE code='sh.600000'").fetchone()
        assert row["industry"] is None
        assert row["pb"] is None
        assert row["high_52w"] is None
        assert row["full_name"] == "合法全称"
        assert row["llm_backfill_at"]
        assert n > 0

    def test_no_valid_fill_keeps_timestamp_null(self, conn):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        target = {"code": "sh.600000", "code_name": "测试", "missing": ["pb"]}
        n = llm_backfill.backfill_one(conn, "stock", target, {"pb": -1})
        row = conn.execute("SELECT * FROM stock_info WHERE code='sh.600000'").fetchone()
        assert row["pb"] is None
        assert row["llm_backfill_at"] is None
        assert n == 0

    def test_etf_backfill(self, conn):
        conn.execute("INSERT INTO etf_info (code) VALUES ('sh.510010')")
        target = {"code": "sh.510010", "code_name": "上证50ETF", "missing": ["category", "manager", "fundScale"]}
        n = llm_backfill.backfill_one(conn, "etf", target, {
            "category": "宽基",
            "manager": "华夏基金",
            "fundScale": 5e9,
        })
        row = conn.execute("SELECT * FROM etf_info WHERE code='sh.510010'").fetchone()
        assert row["category"] == "宽基"
        assert row["manager"] == "华夏基金"
        assert row["fund_scale"] == 5e9
        assert row["llm_backfill_at"]
        assert n == 3


class TestBuildPrompt:
    def test_includes_missing_fields(self):
        prompt = llm_backfill.build_prompt("stock", "sh.600000", "浦发银行", ["industry", "pb"])
        assert "sh.600000" in prompt
        assert "浦发银行" in prompt
        assert "industry" in prompt
        assert "pb" in prompt
        assert "category" not in prompt


class TestRun:
    def test_run_calls_llm_and_backfills(self, conn, monkeypatch):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        captured = {}
        def fake_call(prompt, *args, **kwargs):
            captured["prompt"] = prompt
            return {"industry": "银行", "pb": 0.8, "fullName": "浦发银行"}
        monkeypatch.setattr(llm_backfill, "call_llm", fake_call)
        handled, filled = llm_backfill.run(conn, "stock", None, 10, "url", "model", "key", 1000)
        assert handled == 1
        assert filled == 1
        row = conn.execute("SELECT * FROM stock_info WHERE code='sh.600000'").fetchone()
        assert row["industry"] == "银行"
        assert row["pb"] == 0.8

    def test_run_continues_on_error(self, conn, monkeypatch):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600001')")
        def fake_call(prompt, *args, **kwargs):
            if "sh.600000" in prompt:
                raise RuntimeError("boom")
            return {"industry": "银行"}
        monkeypatch.setattr(llm_backfill, "call_llm", fake_call)
        handled, filled = llm_backfill.run(conn, "stock", None, 10, "url", "model", "key", 1000)
        assert handled == 1
        assert filled == 1
