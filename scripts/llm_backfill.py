#!/usr/bin/env python3
"""LLM 补齐基础信息缺失字段（股票 / ETF）。

与 backend 的分析打分分离：本脚本只负责把 BaoStock 无法直接获取的字段
（股票：industry/last_amount/pb/full_name/total_market_cap/high_52w/low_52w；
ETF：category/manager/fund_scale）通过 LLM 补齐，不影响分析打分任务。

回填规则（与后端原实现一致，防 LLM 幻觉覆盖）：
- 仅回填空字段：目标列已有值（非 NULL / 非空串）不覆盖。
- 入库前校验：字符串非空且限长；数值有限非负（52 周高低须为正）。
- 每次回填写入 llm_backfill_at 时间戳，便于追溯。

用法示例：
    # 补齐 A 股缺失字段（默认 both，可用 --type stock/etf 限定）
    python llm_backfill.py --db ../data/market.db --type stock --limit 50

    # 只处理指定代码
    python llm_backfill.py --db ../data/market.db --codes sh.600000,sz.159915

    # 仅打印将补齐的清单而不调用 LLM
    python llm_backfill.py --db ../data/market.db --dry-run
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASE_URL = "https://api.openai.com/v1"

# 各类型待补齐字段 -> 目标列。value 为 None 表示"对象字段"，由 LLM JSON 取值。
LLM_FIELDS = {
    "stock": {
        "industry": "industry",
        "lastAmount": "last_amount",
        "pb": "pb",
        "fullName": "full_name",
        "totalMarketCap": "total_market_cap",
        "high52w": "high_52w",
        "low52w": "low_52w",
    },
    "etf": {
        "category": "category",
        "manager": "manager",
        "fundScale": "fund_scale",
    },
}

# 字符串字段最大长度（防 LLM 幻觉超长文本）
MAX_STRLEN = {"industry": 100, "fullName": 200, "category": 100, "manager": 200}


def _is_empty(value):
    return value is None or value == ""


def _validate(src, value):
    """校验 LLM 返回字段：字符串非空且限长；数值有限非负、52周高低须为正。"""
    if src in ("lastAmount", "pb", "totalMarketCap", "high52w", "low52w", "fundScale"):
        # 数值字段须为数值类型（bool 是 int 子类，排除）；不接受字符串数字
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        num = float(value)
        if not _isfinite(num):
            return None
        if src in ("high52w", "low52w"):
            if num <= 0:
                return None
        elif num < 0:
            return None
        return num
    # 字符串字段：须为字符串、非空且不超长
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    limit = MAX_STRLEN.get(src, 100)
    if len(trimmed) > limit:
        return None
    return trimmed


def _isfinite(x):
    return x == x and x != float("inf") and x != float("-inf")


def missing_targets(conn, security_type, codes=None):
    """返回（code, code_name, 缺失字段 json 键列表）列表。"""
    mapping = LLM_FIELDS[security_type]
    table = "stock_info" if security_type == "stock" else "etf_info"
    placeholders = " OR ".join(f'("{col}" IS NULL OR "{col}" = \'\')' for col in mapping.values())
    sql = f'SELECT code, code_name FROM {table} WHERE ({placeholders})'
    params = []
    if codes:
        qs = ", ".join("?" for _ in codes)
        sql += f" AND code IN ({qs})"
        params = list(codes)
    rows = conn.execute(sql, params).fetchall()
    # 只保留确实缺失（NULL/空）的字段
    result = []
    for row in rows:
        cur = conn.execute(
            f'SELECT {", ".join(mapping.values())} FROM {table} WHERE code = ?',
            (row["code"],),
        ).fetchone()
        missing = [
            src for src, col in mapping.items()
            if _is_empty(cur[col])
        ]
        if missing:
            result.append({"code": row["code"], "code_name": row["code_name"],
                           "missing": missing})
    return result


def build_prompt(security_type, code, code_name, missing):
    label = "A 股" if security_type == "stock" else "ETF"
    fields_desc = {
        "industry": "所属行业",
        "lastAmount": "最后交易日成交额（元，数值）",
        "pb": "市净率（数值）",
        "fullName": "公司全称",
        "totalMarketCap": "总市值（元，数值）",
        "high52w": "52 周最高价（元，数值）",
        "low52w": "52 周最低价（元，数值）",
        "category": "ETF 类别（宽基/行业/主题/策略/跨境/债券）",
        "manager": "管理人（基金公司名称）",
        "fundScale": "基金规模（元，数值）",
    }
    fields = "\n".join(f"- {src}: {fields_desc[src]}" for src in missing)
    return (
        f"你是一位严谨的证券信息补全助手。请根据证券代码与名称，尽可能准确补全以下"
        f"缺失的基础信息字段，切勿编造无法合理推断的数值（如无把握可省略该项）。\n\n"
        f"## 标的信息\n- 类型：{label}\n- 代码：{code}\n- 名称：{code_name}\n\n"
        f"## 需补全字段（仅这些字段，缺失项可省略）\n{fields}\n\n"
        f"## 输出要求\n严格输出一个 JSON 对象，不要包含多余文字或 Markdown 代码块。\n"
        f"直接输出 JSON 即可。"
    )


def call_llm(prompt, base_url, model, api_key, timeout_ms):
    """调用 OpenAI 兼容端点，返回解析后的 JSON 对象；失败抛异常。"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = json.dumps({
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system",
             "content": "你是一个严谨的证券信息补全助手，只输出符合要求的 JSON。"},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def backfill_one(conn, security_type, target, llm_obj):
    """将 LLM 结果回填到 info 表（仅空字段 + 校验 + 时间戳）。返回回填字段数。"""
    mapping = LLM_FIELDS[security_type]
    table = "stock_info" if security_type == "stock" else "etf_info"
    sets = []
    params = []
    cur = conn.execute(
        f'SELECT * FROM {table} WHERE code = ?', (target["code"],)).fetchone()
    for src, col in mapping.items():
        if not _is_empty(cur[col]):  # 已有值不覆盖
            continue
        raw = llm_obj.get(src) if isinstance(llm_obj, dict) else None
        if raw is None:
            continue
        val = _validate(src, raw)
        if val is None:
            continue
        sets.append(f'{col} = ?')
        params.append(val)
    if not sets:
        return 0
    sets.append("llm_backfill_at = ?")
    params.append(datetime.now().astimezone().isoformat())
    params.append(target["code"])
    conn.execute(f'UPDATE {table} SET {", ".join(sets)} WHERE code = ?', params)
    conn.commit()
    return len(sets) - 1  # 减去 llm_backfill_at


def run(conn, security_type, codes, limit, base_url, model, api_key, timeout_ms):
    """执行补齐任务，返回 (处理数, 成功回填字段数)。"""
    handled = 0
    filled = 0
    targets = missing_targets(conn, security_type, codes)
    if limit:
        targets = targets[:limit]
    for i, t in enumerate(targets, 1):
        try:
            prompt = build_prompt(security_type, t["code"], t["code_name"], t["missing"])
            llm_obj = call_llm(prompt, base_url, model, api_key, timeout_ms)
            n = backfill_one(conn, security_type, t, llm_obj)
            filled += 1 if n else 0
            handled += 1
            log.info("[%d/%d] %s %s 回填 %d 项", i, len(targets),
                     security_type, t["code"], n)
        except Exception as exc:  # noqa: BLE001 —— 单只失败不中断整体
            log.warning("[%d/%d] %s %s 失败: %s", i, len(targets),
                        security_type, t["code"], exc)
    return handled, filled


def build_parser():
    parser = argparse.ArgumentParser(description="LLM 补齐基础信息缺失字段")
    parser.add_argument("--db", default=os.path.join(ROOT, "data", "market.db"),
                        help="SQLite 数据库路径")
    parser.add_argument("--type", choices=("stock", "etf", "both"), default="both",
                        help="补齐标的类型，默认 both")
    parser.add_argument("--codes", default=None,
                        help="逗号分隔证券代码（可选，缺省处理全部缺失标的）")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多处理的标的数（可选）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印将补齐的清单，不调用 LLM")
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
                        help=f"LLM 端点地址，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o"),
                        help="LLM 模型名，默认 gpt-4o（可用 LLM_MODEL 覆盖）")
    parser.add_argument("--timeout-ms", type=int, default=60000,
                        help="单次 LLM 调用超时毫秒，默认 60000")
    return parser


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        sys.exit("需设置环境变量 LLM_API_KEY 才能调用 LLM；可用 --dry-run 先行预览")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    codes = args.codes.split(",") if args.codes else None

    types = ("stock", "etf") if args.type == "both" else (args.type,)
    total_handled = total_filled = 0
    for security_type in types:
        targets = missing_targets(conn, security_type, codes)
        if args.dry_run:
            log.info("[%s] 待补齐 %d 个标的：%s", security_type, len(targets),
                     ", ".join(f"{t['code']}({t['code_name']}:{','.join(t['missing'])})"
                               for t in targets[:20]))
            total_handled += len(targets)
            continue
        handled, filled = run(conn, security_type, codes, args.limit,
                              args.base_url, args.model, api_key, args.timeout_ms)
        total_handled += handled
        total_filled += filled
    log.info("完成：处理 %d 个标的，成功回填 %d 只有值变更",
             total_handled, total_filled)
    conn.close()


if __name__ == "__main__":
    main()
