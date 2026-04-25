"""Flask 扩展集中初始化模块 —— 统一管理扩展、错误处理器、模板过滤器与基础路由"""

from datetime import datetime

from flask import Flask, jsonify, request
from flask_login import LoginManager, UserMixin
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError

from config import Config
from utils.exceptions import AppException
from utils.response import handle_app_exception, make_json, error_response
from utils.validators import safe_json_load
from models.database import close_db, get_db

# ---------- 创建扩展实例（暂不绑定 app） ----------
login_manager = LoginManager()
csrf = CSRFProtect()


# ---------- Flask-Login 用户模型 ----------
class User(UserMixin):
    """Flask-Login 用户模型类，封装用户身份与权限信息。"""

    def __init__(self, user_id: int, username: str, role: str, workshop: str = None):
        self.id = user_id
        self.username = username
        self.role = role
        self.workshop = workshop


@login_manager.user_loader
def load_user(user_id: int):
    """通过用户 ID 加载用户（Flask-Login 回调）。

    使用延迟导入 UserDAO 避免循环依赖。
    """
    from models.user import UserDAO

    conn = get_db()
    try:
        user = UserDAO.get_by_id(conn, int(user_id))
        if user:
            return User(user["id"], user["username"], user["role"], user.get("workshop"))
    finally:
        conn.close()
    return None


def init_extensions(app: Flask) -> None:
    """初始化所有 Flask 扩展、错误处理器、模板过滤器与公共路由。

    Args:
        app: Flask 应用实例
    """
    # 1. 初始化扩展
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "请先登录"

    csrf.init_app(app)

    # 2. 注册请求/应用上下文清理钩子
    app.teardown_appcontext(close_db)

    # 3. CSRF 错误处理器
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e: CSRFError):
        """区分 API 请求与普通页面请求的 CSRF 错误响应。"""
        if request.path.startswith("/api/"):
            return make_json(
                error_response("CSRF token missing or invalid", 400), 400
            )
        return "CSRF验证失败，请刷新页面重试", 400

    # 4. 全局业务异常处理器（覆盖所有 AppException 子类）
    @app.errorhandler(AppException)
    def handle_app_exc(e: AppException):
        """统一处理业务异常，返回规范化 JSON 或文本响应。"""
        if request.path.startswith("/api/"):
            return handle_app_exception(e)
        # 非 API 路由：返回简短文本（避免泄露过多信息）
        return e.message, e.error_code

    # 5. 全局兜底异常处理器（不泄露敏感信息）
    @app.errorhandler(Exception)
    def handle_generic_exception(e: Exception):
        """捕获未处理异常，API 返回 500 JSON，页面返回文本。

        注意：werkzeug.exceptions.HTTPException（如 404）是正常的 HTTP 路由不匹配，
        不记录错误日志，避免 Chrome DevTools 等自动探测请求的日志污染。
        """
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException):
            # 正常的 HTTP 异常（404, 405 等），直接透传，不记录 traceback
            return e

        # 真正的未处理异常（代码 bug），才记录 ERROR 日志
        app.logger.error(f"未处理异常: {str(e)}", exc_info=True)
        if request.path.startswith("/api/"):
            if isinstance(e, ValueError):
                return make_json(error_response(str(e), 400), 400)
            return make_json(error_response("服务器内部错误", 500), 500)
        return "服务器内部错误，请联系管理员", 500

    # 6. favicon 豁免（避免 CSRF 与登录拦截）
    @app.route("/favicon.ico")
    @csrf.exempt
    def favicon():
        return "", 204

    # 7. 健康检查
    @app.route("/health")
    @csrf.exempt
    def health_check():
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
        })

    # 8. 注册模板过滤器
    app.jinja_env.filters["safe_json_load"] = safe_json_load

    # 9. 上传目录确保存在
    Config.get_upload_full_path()
