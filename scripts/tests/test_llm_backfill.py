"""llm_backfill 模块单元测试：缺失字段识别 / 校验 / 回填 / 重试，不打网络。"""
import json
import re
import sqlite3
import urllib.error

import pytest

import llm_backfill
from conftest import SCHEMA

UTC_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


def _fake_urlopen_response(obj):
    """构造 urllib urlopen 成功响应替身：read() 返回含 LLM JSON 的 OpenAI 响应体。"""
    body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]}
    ).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body

    return _Resp()


def _http_error(req, code, msg="err"):
    return urllib.error.HTTPError(req.full_url, code, msg, {}, None)


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

    def test_single_query_not_per_row(self, conn):
        for i in range(10):
            conn.execute("INSERT INTO stock_info (code) VALUES (?)", (f"sh.6000{i:02d}",))
        seen = []
        conn.set_trace_callback(lambda sql: seen.append(sql))
        targets = llm_backfill.missing_targets(conn, "stock")
        conn.set_trace_callback(None)
        selects = [s for s in seen if s.lstrip().startswith("SELECT")]
        assert len(targets) == 10
        assert len(selects) == 1  # 字段列随主查询一次返回，无每行二次 SELECT


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

    def test_timestamp_uses_utc_z_format(self, conn):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        target = {"code": "sh.600000", "code_name": "测试", "missing": ["industry"]}
        llm_backfill.backfill_one(conn, "stock", target, {"industry": "银行"})
        row = conn.execute("SELECT * FROM stock_info WHERE code='sh.600000'").fetchone()
        # 与后端 new Date().toISOString()（UTC + 'Z'）同格式，便于对齐追溯
        assert UTC_ISO_RE.fullmatch(row["llm_backfill_at"])
        assert "+" not in row["llm_backfill_at"]


class TestBuildPrompt:
    def test_includes_missing_fields(self):
        prompt = llm_backfill.build_prompt("stock", "sh.600000", "浦发银行", ["industry", "pb"])
        assert "sh.600000" in prompt
        assert "浦发银行" in prompt
        assert "industry" in prompt
        assert "pb" in prompt
        assert "category" not in prompt

    def test_code_name_none_falls_back_to_code(self):
        prompt = llm_backfill.build_prompt("stock", "sh.600000", None, ["industry"])
        assert "None" not in prompt
        assert "sh.600000" in prompt

    def test_code_name_blank_falls_back_to_code(self):
        prompt = llm_backfill.build_prompt("etf", "sh.510010", "", ["category"])
        assert "None" not in prompt
        assert "sh.510010" in prompt


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

    def test_run_passes_max_retries(self, conn, monkeypatch):
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        seen = {}
        def fake_call(prompt, *args, **kwargs):
            seen["args"] = args
            return {"industry": "银行"}
        monkeypatch.setattr(llm_backfill, "call_llm", fake_call)
        llm_backfill.run(conn, "stock", None, 10, "url", "model", "key", 1000, max_retries=5)
        assert seen["args"][-1] == 5


class TestBackoffMs:
    def test_ratelimited_starts_higher(self):
        assert llm_backfill.backoff_ms(0, rate_limited=True) == 500
        assert llm_backfill.backoff_ms(0, rate_limited=False) == 200

    def test_exponential_with_cap(self):
        assert llm_backfill.backoff_ms(1, rate_limited=True) == 1000
        assert llm_backfill.backoff_ms(2, rate_limited=True) == 2000  # 封顶 2s
        assert llm_backfill.backoff_ms(4, rate_limited=False) == 2000


class TestCallLlm:
    def test_success(self, monkeypatch):
        calls = {"n": 0}
        def fake_urlopen(req, timeout):
            calls["n"] += 1
            return _fake_urlopen_response({"industry": "银行"})
        monkeypatch.setattr(llm_backfill.urllib.request, "urlopen", fake_urlopen)
        got = llm_backfill.call_llm("p", "http://x/v1", "m", "k", 1000)
        assert got == {"industry": "银行"}
        assert calls["n"] == 1

    def test_retries_429_then_succeeds(self, monkeypatch):
        calls = {"n": 0}
        sleeps = []
        def fake_urlopen(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(req, 429)
            return _fake_urlopen_response({"industry": "银行"})
        monkeypatch.setattr(llm_backfill.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(llm_backfill.time, "sleep", sleeps.append)
        got = llm_backfill.call_llm("p", "http://x/v1", "m", "k", 1000)
        assert got == {"industry": "银行"}
        assert calls["n"] == 2
        assert sleeps == [500]  # 429 首退避 500ms

    def test_retries_on_urlerror(self, monkeypatch):
        calls = {"n": 0}
        def fake_urlopen(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("refused")
            return _fake_urlopen_response({"industry": "银行"})
        monkeypatch.setattr(llm_backfill.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(llm_backfill.time, "sleep", lambda s: None)
        got = llm_backfill.call_llm("p", "http://x/v1", "m", "k", 1000)
        assert calls["n"] == 2

    def test_non_429_4xx_not_retried(self, monkeypatch):
        calls = {"n": 0}
        def fake_urlopen(req, timeout):
            calls["n"] += 1
            raise _http_error(req, 401)
        monkeypatch.setattr(llm_backfill.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(llm_backfill.time, "sleep", lambda s: None)
        with pytest.raises(urllib.error.HTTPError):
            llm_backfill.call_llm("p", "http://x/v1", "m", "k", 1000, max_retries=3)
        assert calls["n"] == 1  # 鉴权类错误重试无意义

    def test_exhausts_retries_after_max_retries(self, monkeypatch):
        calls = {"n": 0}
        sleeps = []
        def fake_urlopen(req, timeout):
            calls["n"] += 1
            raise _http_error(req, 503)
        monkeypatch.setattr(llm_backfill.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(llm_backfill.time, "sleep", sleeps.append)
        with pytest.raises(urllib.error.HTTPError):
            llm_backfill.call_llm("p", "http://x/v1", "m", "k", 1000, max_retries=2)
        assert calls["n"] == 3  # 1 次尝试 + 2 次重试
        assert sleeps == [200, 400]  # 503 非 429：200ms 起步，指数退避


class TestCliRoundTrip:
    """mock LLM 的 CLI 端到端：main() 全链路（缺识别 -> LLM -> 校验 -> 回填）。"""

    def test_main_backfills_stock(self, tmp_path, monkeypatch):
        db = tmp_path / "cli.db"
        conn = sqlite3.connect(db)
        with open(SCHEMA, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute("INSERT INTO stock_info (code) VALUES ('sh.600000')")
        conn.commit()

        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        calls = {"n": 0}
        def fake_urlopen(req, timeout):
            calls["n"] += 1
            return _fake_urlopen_response({"industry": "银行", "pb": 0.8})
        monkeypatch.setattr(llm_backfill.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(llm_backfill.time, "sleep", lambda s: None)

        llm_backfill.main(["--db", str(db), "--type", "stock"])
        assert calls["n"] == 1

        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM stock_info WHERE code='sh.600000'").fetchone()
        conn.close()
        assert row["industry"] == "银行"
        assert row["pb"] == 0.8
        assert UTC_ISO_RE.fullmatch(row["llm_backfill_at"])
