"""统一输入验证函数 —— 所有验证失败时抛出 ValidationError，不返回错误码"""

import json
from datetime import datetime
from typing import Any, Optional

from .exceptions import ValidationError


def validate_str(val: Any, max_len: int = 50, required: bool = True) -> Optional[str]:
    """校验字符串值。

    Args:
        val: 输入值
        max_len: 最大允许长度
        required: 是否必填，True 时 val 为 None 或空字符串将抛出异常

    Returns:
        去除首尾空白后的字符串；若 val 为 None 且 required=False，则返回 None
    """
    if required and (val is None or (isinstance(val, str) and val.strip() == "")):
        raise ValidationError("字段不能为空")
    if val is None:
        return None
    val = str(val).strip()
    if len(val) > max_len:
        raise ValidationError(f"长度不能超过 {max_len} 字符")
    return val


def validate_int(val: Any, min_val: int = 0, max_val: int = 1000000) -> int:
    """校验整数值。

    Args:
        val: 输入值，需能转为 int
        min_val: 最小允许值（含）
        max_val: 最大允许值（含）

    Returns:
        转换后的 int
    """
    try:
        val = int(val)
    except (TypeError, ValueError):
        raise ValidationError("必须是整数")
    if val < min_val or val > max_val:
        raise ValidationError(f"数值必须在 {min_val} 到 {max_val} 之间")
    return val


def validate_float(val: Any, min_val: float = 0.0, max_val: float = 1000000.0) -> float:
    """校验浮点数值。

    Args:
        val: 输入值，需能转为 float
        min_val: 最小允许值（含）
        max_val: 最大允许值（含）

    Returns:
        转换后的 float
    """
    try:
        val = float(val)
    except (TypeError, ValueError):
        raise ValidationError("必须是数字")
    if val < min_val or val > max_val:
        raise ValidationError(f"数值必须在 {min_val} 到 {max_val} 之间")
    return val


def validate_date(val: Any) -> str:
    """校验日期格式必须为 YYYY-MM-DD。

    Args:
        val: 输入日期字符串

    Returns:
        去除空白后的日期字符串
    """
    if val is None or (isinstance(val, str) and val.strip() == ""):
        raise ValidationError("日期不能为空")
    val = str(val).strip()
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("日期格式必须为 YYYY-MM-DD")
    return val


def validate_choice(val: Any, allowed_list: list) -> Any:
    """校验值必须在允许列表中。

    Args:
        val: 输入值
        allowed_list: 允许的值列表

    Returns:
        原值（验证通过后原样返回）
    """
    if val not in allowed_list:
        allowed_str = ", ".join(str(v) for v in allowed_list)
        raise ValidationError(f"无效值 '{val}'，允许的值：{allowed_str}")
    return val


def safe_json_load(s: Any, default: Any = None) -> Any:
    """安全解析 JSON 字符串，解析失败返回默认值。

    Args:
        s: JSON 字符串
        default: 解析失败时的返回值，默认返回空 dict

    Returns:
        解析后的 Python 对象，或 default
    """
    if default is None:
        default = {}
    if s is None:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def validate_size_range(start: Any, end: Any) -> tuple:
    """校验码段范围（鞋码起始与结束）。

    校验规则：
        - start、end 必须为 1~99 的整数
        - end - start 必须 ≤ 20（防止异常大范围）
        - end 必须 ≥ start

    Args:
        start: 起始码
        end: 结束码

    Returns:
        (start_int, end_int) 元组
    """
    start = validate_int(start, min_val=1, max_val=99)
    end = validate_int(end, min_val=1, max_val=99)
    if end < start:
        raise ValidationError("结束码必须大于等于起始码")
    if end - start > 20:
        raise ValidationError("码段跨度不能超过 20")
    return start, end
