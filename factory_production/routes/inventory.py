"""库存路由层 —— 处理库存页面、库存 API、图片上传、批量入库（模板下载+文件上传）。

所有 API 返回格式与原始系统保持一致。
"""

import csv
import io
import logging
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response
from flask_login import login_required, current_user

from extensions import csrf
from services.inventory_service import InventoryService
from services.order_service import OrderService
from utils.exceptions import AppException
from utils.security import allowed_file
from utils.validators import safe_json_load
from config import Config

logger = logging.getLogger(__name__)

inventory_bp = Blueprint("inventory", __name__)

_TYPE_NAMES = {
    "blow_sole": "吹气鞋底",
    "pu_sole": "PU鞋底",
    "paint_sole": "喷漆鞋底",
    "plastic_upper": "滴塑帮面",
    "domestic": "国内鞋材",
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
# 库存列表页面
# ============================================================

@inventory_bp.route("/inventory")
@login_required
def inventory_list():
    inventory_type = request.args.get("type", "blow_sole")
    search = request.args.get("search", "").strip()

    materials = InventoryService.list_inventory(
        inventory_type=inventory_type, search=search
    )
    return render_page(
        "inventory.html",
        materials=materials,
        inventory_type=inventory_type,
        search=search,
        type_names=_TYPE_NAMES,
    )


# ============================================================
# 库存删除
# ============================================================

@inventory_bp.route("/inventory/<int:id>/delete", methods=["POST"])
@login_required
def inventory_delete(id):
    if current_user.role != "admin":
        flash("无权限", "danger")
        return redirect(url_for("inventory_list"))

    try:
        InventoryService.delete_inventory(id)
        flash("库存记录已删除", "success")
    except AppException as e:
        flash(str(e), "danger")
    except Exception as e:
        logger.error(f"删除库存失败: {e}", exc_info=True)
        flash("删除失败", "danger")

    return redirect(url_for("inventory_list"))


# ============================================================
# API: 搜索库存 —— 前端期望直接返回数组
# ============================================================

@inventory_bp.route("/api/inventory/search")
@login_required
def api_inventory_search():
    q = request.args.get("q", "").strip()
    inv_type = request.args.get("type", "").strip()
    color = request.args.get("color", "").strip()

    try:
        results = InventoryService.search_inventory(q=q, inv_type=inv_type, color=color)
        return jsonify(results)
    except Exception as e:
        logger.exception("api_inventory_search error")
        return jsonify([]), 500


# ============================================================
# API: 批量入库 —— 返回 {"success": true, "count": N}
# ============================================================

@inventory_bp.route("/api/inventory/batch_add", methods=["POST"])
@csrf.exempt
@login_required
def api_inventory_batch_add():
    if current_user.role != "admin":
        return jsonify({"success": False, "error": "无权限"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400

    inventory_type = data.get("inventory_type")
    items = data.get("items", [])
    size_start = data.get("size_start", 37)
    size_end = data.get("size_end", 42)

    # 给每个 item 添加 size_start/size_end
    for item in items:
        item.setdefault("size_start", size_start)
        item.setdefault("size_end", size_end)

    try:
        count = InventoryService.batch_inbound(
            inventory_type=inventory_type,
            items=items,
            operator_id=current_user.id,
        )
        return jsonify({"success": True, "count": count})
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception("api_inventory_batch_add error")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 更新库存信息
# ============================================================

@inventory_bp.route("/api/inventory/<int:id>/update", methods=["POST"])
@csrf.exempt
@login_required
def api_inventory_update(id):
    if current_user.role != "admin":
        return jsonify({"success": False, "error": "无权限"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400

    try:
        InventoryService.update_inventory_info(
            inv_id=id,
            product_code=data.get("product_code", "").strip(),
            material_name=data.get("material_name", "").strip(),
            color=data.get("color", "").strip(),
            notes=data.get("notes", "").strip(),
            size_start=data.get("size_start", 37),
            size_end=data.get("size_end", 42),
        )
        return jsonify({"success": True})
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception("api_inventory_update error")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 上传图片 (兼容 /api/upload_image 和 /api/upload_order_image)
# ============================================================

@inventory_bp.route("/api/upload_order_image", methods=["POST"])
@inventory_bp.route("/api/upload_image", methods=["POST"])
@csrf.exempt
@login_required
def upload_order_image():
    """上传图片 API。支持字段名 'file' 和 'image'。"""
    # 前端可能用 'file' 或 'image' 字段名
    file = request.files.get("file") or request.files.get("image")
    if not file:
        return jsonify({"success": False, "error": "没有文件"}), 400
    if file.filename == "":
        return jsonify({"success": False, "error": "空文件名"}), 400
    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "不支持的文件类型"}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"

    from pathlib import Path
    upload_path = Config.get_upload_full_path()
    filepath = upload_path / filename
    file.save(str(filepath))

    url = f"/static/uploads/orders/{filename}"
    return jsonify({"success": True, "url": url, "filename": filename})


# ============================================================
# API: 获取订单图片
# ============================================================

@inventory_bp.route("/api/order/<int:order_id>/images")
@login_required
def api_order_images(order_id):
    try:
        order = OrderService.get_order_detail(order_id)
        images_raw = order["order"].get("images") or "[]"
        images = safe_json_load(images_raw, [])
        return jsonify({"images": images})
    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception("api_order_images error")
        return jsonify({"success": False, "error": "服务器内部错误"}), 500


# ============================================================
# API: 下载批量入库模板（CSV 格式）
# ============================================================

@inventory_bp.route("/api/inventory/download_template")
@login_required
def api_inventory_download_template():
    """下载批量入库 CSV 模板。

    列名根据 size_start/size_end 参数动态生成。
    默认码段范围 37-42（6 个码段）。

    Query Args:
        size_start: 起始码（默认 37）
        size_end: 结束码（默认 42）
    """
    try:
        size_start = int(request.args.get("size_start", 37))
        size_end = int(request.args.get("size_end", 42))
    except (ValueError, TypeError):
        size_start, size_end = 37, 42

    # 校验并限制范围
    if size_start < 1 or size_start > 99:
        size_start = 37
    if size_end < size_start or size_end > size_start + 6:
        size_end = size_start + 5

    # 生成码段列名
    seg_labels = [f"{size_start + i}码" for i in range(size_end - size_start + 1)]

    # 构建 CSV 内容
    header = "货号,材料名称,颜色," + ",".join(seg_labels) + ",备注\n"
    example_sizes = ",".join(["10"] * len(seg_labels))
    example = f"示例货号001,示例材料,红色,{example_sizes},测试数据\n"
    csv_content = header + example

    filename = f"inventory_template_{size_start}_{size_end}.csv"

    response = Response(
        csv_content.encode("utf-8-sig"),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )
    return response


# ============================================================
# API: 上传批量入库文件（CSV/Excel）
# ============================================================

@inventory_bp.route("/api/inventory/upload_batch", methods=["POST"])
@csrf.exempt
@login_required
def api_inventory_upload_batch():
    """上传文件批量入库。

    支持 CSV 格式（UTF-8 编码）。
    列：货号,材料名称,颜色,37码,38码,39码,40码,41码,42码,备注

    返回: {"success": true, "count": N}
    """
    if current_user.role != "admin":
        return jsonify({"success": False, "error": "无权限"}), 403

    inventory_type = request.form.get("inventory_type", "blow_sole")

    # 获取上传的文件
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "请选择文件"}), 400
    if file.filename == "":
        return jsonify({"success": False, "error": "文件名为空"}), 400

    # 获取码段范围
    try:
        size_start = int(request.form.get("size_start", 37))
        size_end = int(request.form.get("size_end", 42))
    except (ValueError, TypeError):
        size_start, size_end = 37, 42
    if size_start < 1 or size_start > 99:
        size_start = 37
    if size_end < size_start or size_end > size_start + 6:
        size_end = size_start + 5
    seg_count = size_end - size_start + 1

    # 解析 CSV
    items = []
    try:
        # 读取文件内容
        file_content = file.read()

        # 尝试多种编码
        for encoding in ["utf-8-sig", "utf-8", "gbk", "gb2312"]:
            try:
                text = file_content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return jsonify({"success": False, "error": "文件编码无法识别，请使用 UTF-8 或 GBK 编码的 CSV"}), 400

        # 解析 CSV
        reader = csv.reader(io.StringIO(text))
        for idx, row in enumerate(reader):
            if idx == 0:
                # 跳过表头行（如果包含"货号"或"材料"等关键字）
                first_col = row[0].strip() if row else ""
                if first_col in ("货号", "product_code", "", "货号,材料名称,颜色") or "货号" in first_col:
                    continue
            if len(row) < 3 + seg_count:
                continue  # 列数不够，跳过

            product_code = row[0].strip()
            if not product_code:
                continue  # 货号为空，跳过

            items.append({
                "product_code": product_code,
                "material_name": row[1].strip() if len(row) > 1 else "",
                "color": row[2].strip() if len(row) > 2 else "",
                "sizes": [parse_float(row[i]) for i in range(3, 3 + seg_count) if i < len(row)],
                "notes": row[3 + seg_count].strip() if len(row) > 3 + seg_count else "",
                "size_start": size_start,
                "size_end": size_end,
            })

        if not items:
            return jsonify({"success": False, "error": "未解析到有效数据，请检查 CSV 格式"}), 400

        count = InventoryService.batch_inbound(
            inventory_type=inventory_type,
            items=items,
            operator_id=current_user.id,
        )
        return jsonify({"success": True, "count": count})

    except AppException as e:
        return jsonify({"success": False, "error": str(e)}), e.error_code
    except Exception as e:
        logger.exception("api_inventory_upload_batch error")
        return jsonify({"success": False, "error": f"解析失败: {str(e)}"}), 500


def parse_float(val):
    """安全解析浮点数。"""
    if val is None:
        return 0.0
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return 0.0
