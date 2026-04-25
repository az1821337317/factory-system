"""管理路由层 —— 处理用户管理与安全设置。

路由职责：
    GET/POST  /admin/users                  → UserService.list_workers() / 管理用户
    POST      /admin/user/<id>/update       → UserService.admin_update_user() → JSON
    GET/POST  /security_settings            → GET: 渲染页面 / POST: 修改用户名/密码 → 重定向
"""

import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user, logout_user

from services.user_service import UserService
from utils.exceptions import AppException

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)

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
# 用户管理页面
# ============================================================

@admin_bp.route("/admin/users")
@login_required
def admin_users():
    """用户管理页面（仅管理员）。"""
    if current_user.role != "admin":
        flash("无权限", "danger")
        return redirect(url_for("index"))

    # 模板使用索引访问（兼容原始模板），返回 sqlite3.Row 列表
    from models.database import get_db
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, username, role, workshop FROM users WHERE role = 'worker' ORDER BY workshop, username"
        )
        workers = c.fetchall()
    finally:
        conn.close()

    return render_page("user_management.html", workers=workers)


# ============================================================
# 用户更新 API
# ============================================================

@admin_bp.route("/admin/user/<int:user_id>/update", methods=["POST"])
@login_required
def admin_update_user(user_id):
    """管理员更新用户信息（仅管理员）。"""
    if current_user.role != "admin":
        return jsonify({"success": False, "error": "无权限"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400

    new_username = data.get("username", "").strip()
    new_password = data.get("password", "").strip()

    try:
        UserService.admin_update_user(
            user_id=user_id,
            new_username=new_username,
            new_password=new_password,
        )
        return jsonify({"success": True})
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception("admin_update_user error")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# 安全设置
# ============================================================

@admin_bp.route("/security_settings", methods=["GET", "POST"])
@login_required
def security_settings():
    """安全设置页面 — 修改用户名/密码。"""
    if request.method == "POST":
        new_username = request.form.get("new_username", "").strip()
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        # 修改用户名
        if new_username and new_username != current_user.username:
            try:
                UserService.change_username(
                    user_id=current_user.id,
                    new_username=new_username,
                )
                flash("用户名修改成功，请重新登录", "success")
                logout_user()
                return redirect(url_for("login"))
            except AppException as e:
                flash(str(e), "danger")
                return redirect(url_for("security_settings"))

        # 修改密码
        if new_password:
            if not old_password:
                flash("需要原密码", "danger")
                return redirect(url_for("security_settings"))
            if new_password != confirm_password:
                flash("两次密码不一致", "danger")
                return redirect(url_for("security_settings"))

            try:
                UserService.change_password(
                    user_id=current_user.id,
                    old_password=old_password,
                    new_password=new_password,
                )
                flash("密码修改成功，请重新登录", "success")
                logout_user()
                return redirect(url_for("login"))
            except AppException as e:
                flash(str(e), "danger")
                return redirect(url_for("security_settings"))

        flash("未做任何修改", "info")
        return redirect(url_for("security_settings"))

    # GET
    return render_page("security_settings.html")
