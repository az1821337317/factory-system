"""任务路由层 —— 处理车间任务页面与任务相关 API。

路由职责：
    GET  /workshop/tasks                          → 渲染 workshop_task.html
    GET  /api/task/<id>                           → 任务详情 JSON
    POST /api/task/<id>/update_sizes              → 提交进度
    POST /api/task/<id>/complete                  → 全部完成
    POST /api/task/<id>/receive                   → 喷漆接收
    GET  /api/task/<id>/source_colors             → 源库存颜色
    POST /api/task/<id>/complete_assembly_with_sizes → 成型出库
    POST /api/task/<id>/assembly_outbound         → 成型出库(简化)

所有 API 返回格式与原始系统保持一致：
    {"success": true/false, ...扁平字段...}
"""

import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from services.task_service import TaskService
from utils.exceptions import AppException
from utils.response import error_response, make_json

logger = logging.getLogger(__name__)

task_bp = Blueprint("task", __name__)

_WORKSHOP_NAMES = {
    "blow": "吹气车间",
    "pu": "PU车间",
    "paint": "喷漆车间",
    "plastic": "滴塑车间",
    "assembly": "成型车间",
}


def is_mobile():
    user_agent = request.headers.get("User-Agent", "").lower()
    return any(k in user_agent for k in ["mobile", "android", "iphone", "ipad", "phone", "ios"])


def render_page(template_name, **context):
    if is_mobile():
        mobile_template = template_name.replace(".html", "_mobile.html")
        try:
            return render_template(mobile_template, **context)
        except Exception:
            pass
    return render_template(template_name, **context)


# ============================================================
# 权限检查辅助函数
# ============================================================

def _check_task_permission(task_detail):
    """校验当前用户是否有权操作该任务。管理员或同车间 worker 可以。"""
    if current_user.role != "admin" and current_user.workshop != task_detail.get("workshop_code"):
        raise PermissionError("无权限")


# ============================================================
# 车间任务页面
# ============================================================

@task_bp.route("/workshop/tasks")
@login_required
def workshop_tasks():
    if current_user.role == "admin":
        workshop_code = request.args.get("workshop", "blow")
    else:
        workshop_code = current_user.workshop or "blow"

    workshop_name = _WORKSHOP_NAMES.get(workshop_code, workshop_code)

    result = TaskService.list_workshop_tasks(
        workshop_code=workshop_code,
        is_admin=(current_user.role == "admin"),
    )

    # 查询车间列表（管理员导航用）
    workshops = []
    if current_user.role == "admin":
        from models.database import get_db
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("SELECT code, name FROM workshops ORDER BY sequence, name")
            workshops = c.fetchall()
        finally:
            conn.close()

    return render_page(
        "workshop_task.html",
        workshop_code=workshop_code,
        workshop_name=workshop_name,
        pending_tasks=result["pending"],
        completed_tasks=result["completed"],
        is_admin=(current_user.role == "admin"),
        workshops=workshops,
    )


# ============================================================
# API: 任务详情
# ============================================================

@task_bp.route("/api/task/<int:task_id>")
@login_required
def api_task_detail(task_id):
    """获取任务详情。

    返回格式(与原始系统兼容):
    {
        "success": true,
        "task": {...},          # 含 order_no, product_code, images 等
        "colors": [...],        # 颜色明细(含plan/completed)
        "upstream_ready": bool,
        "upstream_info": [...],
        "size_start": int,
        "size_end": int,
        "can_process": int,
        "is_first_workshop": bool,
    }
    """
    try:
        detail = TaskService.get_task_detail(task_id, user=current_user)
        detail["success"] = True
        return jsonify(detail)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except PermissionError:
        return jsonify({"success": False, "error": "无权限"}), 403
    except Exception as e:
        logger.exception(f"api_task_detail error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 提交任务进度
# ============================================================

@task_bp.route("/api/task/<int:task_id>/update_sizes", methods=["POST"])
@login_required
def api_task_update_sizes(task_id):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400

    colors_data = data.get("colors", [])
    mark_all_complete = bool(data.get("mark_all_complete", False))

    try:
        result = TaskService.submit_task_progress(
            task_id=task_id,
            user_id=current_user.id,
            user_role=current_user.role,
            user_workshop=current_user.workshop,
            colors_data=colors_data,
            mark_all_complete=mark_all_complete,
        )
        result["success"] = True
        return jsonify(result)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception(f"api_task_update_sizes error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 标记任务全部完成
# ============================================================

@task_bp.route("/api/task/<int:task_id>/complete", methods=["POST"])
@login_required
def api_task_complete(task_id):
    try:
        result = TaskService.submit_task_progress(
            task_id=task_id,
            user_id=current_user.id,
            user_role=current_user.role,
            user_workshop=current_user.workshop,
            colors_data=[],
            mark_all_complete=True,
        )
        result["success"] = True
        return jsonify(result)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception(f"api_task_complete error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 喷漆接收
# ============================================================

@task_bp.route("/api/task/<int:task_id>/receive", methods=["POST"])
@login_required
def api_task_receive(task_id):
    """喷漆接收 API。

    返回格式:
    {
        "success": true,
        "message": "接收成功",
        "received_quantity": int,      # 累计接收总量
        "colors_received": [...],       # 本次各颜色各码段接收明细
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400

    colors_received = data.get("colors", [])
    if not colors_received:
        return jsonify({"success": False, "error": "没有接收数据"}), 400

    try:
        result = TaskService.receive_paint_materials(
            task_id=task_id,
            user_id=current_user.id,
            user_role=current_user.role,
            colors_received=colors_received,
        )
        result["success"] = True
        result["message"] = "接收成功"
        return jsonify(result)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception(f"api_task_receive error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 喷漆源库存颜色
# ============================================================

@task_bp.route("/api/task/<int:task_id>/source_colors")
@login_required
def api_task_source_colors(task_id):
    try:
        result = TaskService.get_source_colors_for_paint(task_id)
        result["success"] = True
        return jsonify(result)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception(f"api_task_source_colors error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 成型出库（带尺寸）
# ============================================================

@task_bp.route("/api/task/<int:task_id>/complete_assembly_with_sizes", methods=["POST"])
@login_required
def api_complete_assembly_with_sizes(task_id):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400

    colors_data = data.get("colors", [])

    try:
        result = TaskService.assembly_outbound(
            task_id=task_id,
            user_id=current_user.id,
            user_role=current_user.role,
            user_workshop=current_user.workshop,
            colors_data=colors_data,
        )
        result["success"] = True
        return jsonify(result)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception(f"api_complete_assembly error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 成型出库（简化版）
# ============================================================

@task_bp.route("/api/task/<int:task_id>/assembly_outbound", methods=["POST"])
@login_required
def api_assembly_outbound(task_id):
    data = request.get_json() or {}
    colors_data = data.get("colors", [])

    try:
        result = TaskService.assembly_outbound(
            task_id=task_id,
            user_id=current_user.id,
            user_role=current_user.role,
            user_workshop=current_user.workshop,
            colors_data=colors_data,
        )
        result["success"] = True
        return jsonify(result)
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception(f"api_assembly_outbound error: task_id={task_id}")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500
