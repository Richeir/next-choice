"""数据转换工具：类型清洗、市场推断、K 线表名。"""
import math


def to_float(value):
    """把字符串/数值转 float；None/空串/NaN 转 None。"""
    if value is None or value == "":
        return None
    f = float(value)
    if math.isnan(f):
        return None
    return f


_STOCK_SH = ("60", "68")
_STOCK_SZ = ("00", "30")
_ETF_SH = ("51", "52", "53", "55", "56", "58")
_ETF_SZ = ("15", "16")


def market_of(code):
    """由 6 位纯数字 code 的号段推断市场：返回 'SH' / 'SZ'。"""
    prefix = code[:2]
    if prefix in _STOCK_SH + _ETF_SH:
        return "SH"
    if prefix in _STOCK_SZ + _ETF_SZ:
        return "SZ"
    raise ValueError(f"unknown code segment: {code!r}")


def is_etf_code(code):
    """由 6 位纯数字 code 的号段判断是否为 ETF。"""
    return code[:2] in _ETF_SH + _ETF_SZ


def kline_table(kind, freq):
    """返回 K 线表名，如 kline_table('stock','daily') -> 'stock_kline_daily'。"""
    if kind not in ("stock", "etf"):
        raise ValueError(f"unknown kind: {kind!r}")
    if freq not in ("daily", "weekly", "monthly"):
        raise ValueError(f"unknown frequency: {freq!r}")
    return f"{kind}_kline_{freq}"
