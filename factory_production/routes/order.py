"""指令单路由层 —— 处理首页、指令单创建、详情、删除。

路由职责：
    GET  /                     → OrderService.list_orders() → 渲染 index.html
    POST /order/<id>/delete    → 权限检查 → OrderService.delete_order() → 重定向
    GET  /order/<id>           → OrderService.get_order_detail() → 渲染 order_detail.html
    GET  /create_order         → 渲染 create_order.html（含 today, order_type）
    POST /create_order         → 解析复杂表单 → OrderService.create_order() → 重定向
"""

import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from services.order_service import OrderService
from utils.exceptions import AppException
from utils.validators import validate_int

logger = logging.getLogger(__name__)

order_bp = Blueprint("order", __name__)

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
# 首页 — 指令单列表
# ============================================================

@order_bp.route("/")
@login_required
def index():
    """首页路由 — 列出所有指令单，支持搜索。"""
    search = request.args.get("search", "").strip()
    orders = OrderService.list_orders(search=search)
    return render_page("index.html", orders=orders, search=search)


# ============================================================
# 指令单删除
# ============================================================

@order_bp.route("/order/<int:order_id>/delete", methods=["POST"])
@login_required
def delete_order(order_id):
    """删除指令单（仅管理员）。"""
    if current_user.role != "admin":
        flash("无权限删除指令单", "danger")
        return redirect(url_for("index"))

    try:
        OrderService.delete_order(order_id, operator_role=current_user.role)
        flash("指令单已删除", "success")
    except AppException as e:
        flash(str(e), "danger")
    except Exception as e:
        logger.error(f"删除指令单失败: {e}", exc_info=True)
        flash("删除失败", "danger")

    return redirect(url_for("index"))


# ============================================================
# 指令单详情
# ============================================================

@order_bp.route("/order/<int:order_id>")
@login_required
def order_detail(order_id):
    """指令单详情页面。"""
    try:
        detail = OrderService.get_order_detail(order_id)
    except AppException as e:
        flash(str(e), "danger")
        return redirect(url_for("index"))

    # 模板使用索引访问（兼容原始模板），将 dict 转为 sqlite3.Row
    from models.database import get_db
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT id, order_no, product_code, sole_model, upper_model,
                      created_date, status, notes, order_type,
                      sole_source, sole_material_id, upper_source, upper_material_id,
                      other_materials, direct_sale, images,
                      CAST(size_start AS INTEGER) as size_start,
                      CAST(size_end AS INTEGER) as size_end
               FROM prod_orders WHERE id = ?""",
            (order_id,),
        )
        order_row = c.fetchone()
    finally:
        conn.close()

    return render_page(
        "order_detail.html",
        order=order_row if order_row else detail["order"],
        colors=detail["colors"],
        tasks=detail["tasks"],
        sz_start=int(order_row["size_start"] or 37) if order_row else (detail["order"].get("size_start") or 37),
        sz_end=int(order_row["size_end"] or 42) if order_row else (detail["order"].get("size_end") or 42),
    )


# ============================================================
# 创建指令单
# ============================================================

@order_bp.route("/create_order", methods=["GET", "POST"])
@login_required
def create_order():
    """创建指令单路由。

    GET:  渲染创建页面
    POST: 解析复杂表单 → 调用 OrderService.create_order() → 重定向首页
    """
    if request.method == "POST":
        try:
            form_data = _parse_create_order_form(request.form)
            result = OrderService.create_order(
                form_data=form_data, user_id=current_user.id
            )
            flash(f"生产指令单 {result['order_no']} 创建成功", "success")
            return redirect(url_for("index"))
        except AppException as e:
            flash(str(e), "danger")
            return redirect(url_for("create_order"))
        except Exception as e:
            logger.error(f"创建指令单失败: {e}", exc_info=True)
            flash("创建失败，请稍后重试", "danger")
            return redirect(url_for("create_order"))

    # GET: 渲染创建页面
    from datetime import date

    today = date.today().strftime("%Y-%m-%d")
    order_type = request.args.get("type", "blow")
    return render_page("create_order.html", today=today, order_type=order_type)


# ============================================================
# 表单解析辅助函数
# ============================================================

def _parse_create_order_form(form):
    """解析创建指令单的复杂表单数据。

    原始表单包含 color_name[]、size_N_M 等动态字段，
    本函数将其解析为 OrderService.create_order() 期望的 form_data dict。

    Args:
        form: request.form (MultiDict)

    Returns:
        form_data: dict，直接传给 OrderService.create_order()
    """
    # ---- 基础字段 ----
    order_type = form.get("order_type", "blow")
    created_date = form.get("created_date", "").strip()
    notes = form.get("notes", "").strip()
    direct_sale = bool(form.get("direct_sale"))
    plastic_type = form.get("plastic_type", "upper")
    image_urls = form.get("image_urls", "[]")
    size_start = form.get("global_size_start", "37")
    size_end = form.get("global_size_end", "42")

    # ---- 颜色数据解析（防御性重构，参考原 app.py 第780-940行）----
    color_names = form.getlist("color_name[]")

    # 按行收集 size_N_M 数据
    colors_map = {}
    size_keys_found = []

    for key in form:
        if not key.startswith("size_"):
            continue
        parts = key.split("_")
        # 严格校验格式: size_数字_数字（如 size_1_0）
        # 前端命名格式: size_{seg}_{rowIdx}，seg=1~6, rowIdx=0,1,2...
        # 过滤掉 size_start, size_end 等非码段字段
        if len(parts) != 3:
            continue
        try:
            seg = int(parts[1])       # 码段 1~6（前端放在第2段）
            row_idx = int(parts[2])   # 颜色行索引（前端放在第3段）
        except ValueError:
            logger.warning(f"CREATE_ORDER: 忽略非数字 size 字段: {key}")
            continue
        # 校验码段范围 (1~6 对应 size_1~size_6)
        if seg < 1 or seg > 6:
            logger.warning(f"CREATE_ORDER: 忽略超范围码段: {key} (seg={seg})")
            continue
        # 校验行索引
        if row_idx < 0 or row_idx > 100:
            logger.warning(f"CREATE_ORDER: 忽略异常行索引: {key} (row_idx={row_idx})")
            continue

        val_str = form.get(key, "").strip()
        try:
            val = int(val_str) if val_str else 0
        except ValueError:
            val = 0

        if row_idx not in colors_map:
            colors_map[row_idx] = {"sizes": [0] * 6, "name": ""}

        # 防御：同一位置已有非零值时发出警告
        if colors_map[row_idx]["sizes"][seg - 1] != 0 and val != 0:
            logger.warning(
                f"CREATE_ORDER: 码段数据冲突: row={row_idx}, seg={seg}, "
                f"旧值={colors_map[row_idx]['sizes'][seg-1]}, 新值={val}"
            )
        colors_map[row_idx]["sizes"][seg - 1] = val
        size_keys_found.append((row_idx, seg, val))

    # 绑定颜色名到对应行
    for idx, name in enumerate(color_names):
        name = name.strip()
        if name:
            if idx not in colors_map:
                colors_map[idx] = {"sizes": [0] * 6, "name": ""}
            colors_map[idx]["name"] = name

    # 过滤有效数据
    color_data = []
    for idx in sorted(colors_map.keys()):
        item = colors_map[idx]
        if not item["name"]:
            continue
        row_total = sum(item["sizes"])
        if row_total == 0:
            continue
        color_data.append({"name": item["name"], "sizes": item["sizes"]})

    # ---- 型号及来源（根据 order_type）----
    sole_model = ""
    upper_model = ""
    sole_source = None
    sole_material_id = None
    upper_source = None
    upper_material_id = None

    other_sources = form.getlist("other_source[]")
    other_material_ids = form.getlist("other_material_id[]")
    other_materials = []
    for src, mat_id in zip(other_sources, other_material_ids):
        if src:
            other_materials.append(
                {"source": src, "material_id": mat_id if mat_id else None}
            )

    if order_type == "blow":
        sole_model = form.get("sole_model", "").strip()
    elif order_type == "pu":
        sole_model = form.get("sole_model", "").strip()
    elif order_type == "plastic":
        if plastic_type == "sole":
            sole_model = form.get("sole_model", "").strip()
        else:
            upper_model = form.get("upper_model", "").strip()
    elif order_type == "assembly":
        sole_model = form.get("sole_model", "").strip()
        upper_model = form.get("upper_model", "").strip()

    # material_id 转为 int 或 None
    try:
        sole_material_id = int(form.get("sole_material_id")) if form.get("sole_material_id") else None
    except (ValueError, TypeError):
        sole_material_id = None
    try:
        upper_material_id = int(form.get("upper_material_id")) if form.get("upper_material_id") else None
    except (ValueError, TypeError):
        upper_material_id = None

    sole_source = form.get("sole_source")
    upper_source = form.get("upper_source")

    # ---- 构建 form_data ----
    form_data = {
        "order_type": order_type,
        "created_date": created_date,
        "notes": notes,
        "direct_sale": direct_sale,
        "size_start": size_start,
        "size_end": size_end,
        "color_data": color_data,
        "sole_model": sole_model,
        "upper_model": upper_model,
        "product_code": form.get("product_code", "").strip(),
        "sole_source": sole_source,
        "sole_material_id": sole_material_id,
        "upper_source": upper_source,
        "upper_material_id": upper_material_id,
        "other_materials": other_materials,
        "images": image_urls,
        "plastic_type": plastic_type,
    }

    return form_data
