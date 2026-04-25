"""认证路由层 —— 处理登录、登出。

路由职责：
    - GET /login     → 渲染登录页面（含移动端适配）
    - POST /login    → 提取表单 → UserService.authenticate() → login_user() → 重定向
    - GET /logout    → logout_user() → 重定向 /login
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required

from extensions import User
from services.user_service import UserService
from utils.exceptions import AuthenticationError
from utils.security import LoginLimiter

auth_bp = Blueprint("auth", __name__)

# ============================================================
# 移动端适配辅助函数
# ============================================================

def is_mobile():
    """检测当前请求是否来自移动设备。"""
    user_agent = request.headers.get("User-Agent", "").lower()
    mobile_keywords = ["mobile", "android", "iphone", "ipad", "phone", "ios"]
    return any(keyword in user_agent for keyword in mobile_keywords)


def render_page(template_name, **context):
    """自动选择桌面/移动端模板。"""
    if is_mobile():
        mobile_template = template_name.replace(".html", "_mobile.html")
        try:
            return render_template(mobile_template, **context)
        except Exception:
            pass
    return render_template(template_name, **context)


# ============================================================
# 登录
# ============================================================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """登录路由。

    GET:  渲染登录页面（移动端自动切换模板）
    POST: 提取 username/password → 认证 → 登录 → 重定向
    """
    ip = request.remote_addr or "unknown"

    # 检查是否被登录限制器锁定
    if LoginLimiter.is_blocked(ip):
        flash("尝试次数过多，请15分钟后再试", "danger")
        return render_page("login.html")

    if request.method == "GET":
        return render_page("login.html")

    # ---- POST: 处理登录表单 ----
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("用户名和密码不能为空", "danger")
        return render_page("login.html")

    try:
        user_info = UserService.authenticate(
            username=username,
            password=password,
            login_limiter=LoginLimiter,
            ip=ip,
        )
    except AuthenticationError as e:
        flash(str(e), "danger")
        return render_page("login.html")

    # 认证成功：创建 User 对象并登录
    user = User(
        user_id=user_info["id"],
        username=user_info["username"],
        role=user_info["role"],
        workshop=user_info.get("workshop"),
    )
    login_user(user, remember=False)

    # 根据角色重定向
    if user.role == "worker":
        return redirect(url_for("workshop_tasks"))
    return redirect(url_for("index"))


# ============================================================
# 登出
# ============================================================

@auth_bp.route("/logout")
@login_required
def logout():
    """登出路由。"""
    logout_user()
    return redirect(url_for("login"))
