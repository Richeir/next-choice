"""BaoStock 原始数据到 SQLite 的转换工具。

BaoStock 返回的字段全部是 str（数字字符串或空串）。本模块提供：
- 数值/空串 -> REAL / NULL 转换
- 带交易所前缀代码 -> 市场缩写（SH/SZ）推断
- K 线表名（kind x frequency）映射
"""


def to_float(value):
    """把 BaoStock 的字符串数值转为 float；空串/None 转为 None。"""
    if value is None or value == "":
        return None
    return float(value)


def market_of(code):
    """由带交易所前缀的 code 推断市场：sh. -> SH，sz. -> SZ。"""
    if code.startswith("sh."):
        return "SH"
    if code.startswith("sz."):
        return "SZ"
    raise ValueError(f"unknown code prefix: {code!r}")


def kline_table(kind, freq):
    """返回 K 线表名，如 kline_table('stock','daily') -> 'stock_kline_daily'。"""
    if kind not in ("stock", "etf"):
        raise ValueError(f"unknown kind: {kind!r}")
    if freq not in ("daily", "weekly", "monthly"):
        raise ValueError(f"unknown frequency: {freq!r}")
    return f"{kind}_kline_{freq}"
