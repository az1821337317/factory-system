"""统一响应格式模块 —— 规范前后端交互的 JSON 数据结构"""

from typing import Any, Optional

from flask import Response, jsonify, request

from .exceptions import AppException, ValidationError, AuthenticationError, PermissionDenied, ResourceNotFound, BusinessError


def success_response(data: Any = None, message: str = "") -> dict:
    """构造标准成功响应体。

    Returns:
        {"success": True, "data": ..., "message": ...}
    """
    return {"success": True, "data": data, "message": message}


def error_response(error: str, code: int = 400) -> dict:
    """构造标准错误响应体。

    Args:
        error: 错误描述文本
        code: HTTP 状态码（默认 400）

    Returns:
        {"success": False, "error": ..., "code": ...}
    """
    return {"success": False, "error": error, "code": code}


def make_json(data: dict, status_code: int = 200) -> Response:
    """将字典包装为 Flask JSON Response 对象。

    Args:
        data: 响应数据字典
        status_code: HTTP 状态码

    Returns:
        Flask Response 对象
    """
    response = jsonify(data)
    response.status_code = status_code
    return response


def handle_app_exception(e: AppException) -> Response:
    """根据 AppException 子类型返回对应 HTTP 状态码的 JSON 响应。

    Args:
        e: 业务异常实例

    Returns:
        Flask Response 对象
    """
    if isinstance(e, ValidationError):
        return make_json(error_response(e.message, e.error_code), e.error_code)
    if isinstance(e, AuthenticationError):
        return make_json(error_response(e.message, e.error_code), e.error_code)
    if isinstance(e, PermissionDenied):
        return make_json(error_response(e.message, e.error_code), e.error_code)
    if isinstance(e, ResourceNotFound):
        return make_json(error_response(e.message, e.error_code), e.error_code)
    if isinstance(e, BusinessError):
        return make_json(error_response(e.message, e.error_code), e.error_code)
    # 基类兜底
    return make_json(error_response(e.message, e.error_code), e.error_code)
