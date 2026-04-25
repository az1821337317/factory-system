"""订单业务逻辑层 —— 封装指令单创建、查询、删除等核心业务流程。"""

import json
import logging

from models.database import get_transaction_conn, transaction, transaction_immediate
from models.inventory import InventoryDAO
from models.order import OrderDAO, OrderColorDAO
from models.task import TaskDAO
from utils.exceptions import BusinessError, PermissionDenied, ResourceNotFound, ValidationError
from utils.validators import (
    safe_json_load,
    validate_choice,
    validate_date,
    validate_int,
    validate_str,
)

logger = logging.getLogger(__name__)

# 允许的订单类型
_ORDER_TYPES = {"blow", "pu", "plastic", "assembly"}

# 车间代码到库存类型的映射（首道工序生产入库用）
_WORKSHOP_INV_TYPE = {
    "blow": "blow_sole",
    "pu": "pu_sole",
    "plastic": "plastic_upper",
}


class OrderService:
    """订单服务类，处理所有与生产指令单相关的业务操作。"""

    @staticmethod
    @transaction_immediate
    def create_order(form_data: dict, user_id: int) -> dict:
        conn = get_transaction_conn()
        """完整订单创建流程。

        业务流程：
            1. 验证输入参数（日期、类型、颜色、码段）
            2. 根据 order_type 确定 product_code
            3. 生成单号（前缀 + 日期 + 序号）
            4. 创建订单记录
            5. 创建颜色明细
            6. 如果是 assembly 类型：从库存扣减鞋底/帮面材料
            7. 根据 order_type 生成车间任务

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            form_data: 表单数据字典，包含：
                - order_type: 订单类型 (blow/pu/plastic/assembly)
                - created_date: 日期 YYYY-MM-DD
                - notes: 备注（可选）
                - direct_sale: 是否直销（bool）
                - size_start: 起始码（默认37）
                - size_end: 结束码（默认42）
                - color_data: 颜色数据列表 [{"name": str, "sizes": [6 ints]}, ...]
                - sole_model: 鞋底型号（blow/pu/plastic 用）
                - upper_model: 帮面型号（plastic/assembly 用）
                - product_code: 产品型号（assembly 用）
                - sole_source: 鞋底来源（assembly 用）
                - sole_material_id: 鞋底材料库存ID（assembly 用）
                - upper_source: 帮面来源（assembly 用）
                - upper_material_id: 帮面材料库存ID（assembly 用）
                - other_materials: 其他材料列表 [{"source": str, "material_id": int}, ...]
                - images: 图片URL列表的JSON字符串（可选）
            user_id: 创建人用户 ID

        Returns:
            {"order_no": str, "total_pairs": int}

        Raises:
            ValidationError: 参数校验失败
            BusinessError: 库存不足等业务规则违反
        """
        # ---- 1. 基础参数校验 ----
        order_type = validate_choice(form_data.get("order_type"), list(_ORDER_TYPES))
        created_date = validate_date(form_data.get("created_date"))
        notes = validate_str(form_data.get("notes", ""), max_len=200, required=False) or None
        direct_sale = bool(form_data.get("direct_sale"))
        size_start = validate_int(form_data.get("size_start", 37), min_val=1, max_val=99)
        size_end = validate_int(form_data.get("size_end", 42), min_val=1, max_val=99)
        if size_end - size_start != 5:
            size_end = size_start + 5

        # ---- 2. 颜色数据解析与校验 ----
        color_data = form_data.get("color_data", [])
        if not color_data:
            raise ValidationError("请至少添加一个颜色")

        total_pairs = 0
        parsed_colors = []
        for cd in color_data:
            name = cd.get("name", "").strip()
            if not name:
                continue
            sizes = cd.get("sizes", [])
            if len(sizes) != 6:
                raise ValidationError(f"颜色 {name} 的码段数据异常：期望6个码段，实际{len(sizes)}个")
            row_total = sum(sizes)
            if row_total == 0:
                continue
            parsed_colors.append({"name": name, "sizes": sizes})
            total_pairs += row_total

        if not parsed_colors:
            raise ValidationError("请至少填写一个码段的数量")

        # 总数异常检查
        if total_pairs > 50000:
            logger.warning(f"CREATE_ORDER: 总数异常大: {total_pairs}, colors={len(parsed_colors)}")

        # ---- 3. 根据类型确定 product_code 和相关字段 ----
        sole_model = ""
        upper_model = ""
        sole_source = None
        sole_material_id = None
        upper_source = None
        upper_material_id = None
        other_materials = form_data.get("other_materials", []) or []
        images = form_data.get("images", "[]")

        if order_type == "blow":
            sole_model = validate_str(form_data.get("sole_model"), max_len=30, required=True)
            product_code = sole_model
        elif order_type == "pu":
            sole_model = validate_str(form_data.get("sole_model"), max_len=30, required=True)
            product_code = sole_model
        elif order_type == "plastic":
            plastic_type = form_data.get("plastic_type", "upper")
            if plastic_type == "sole":
                sole_model = validate_str(form_data.get("sole_model"), max_len=30, required=True)
                product_code = sole_model
            else:
                upper_model = validate_str(form_data.get("upper_model"), max_len=30, required=True)
                product_code = upper_model
                sole_model = ""
        elif order_type == "assembly":
            product_code = validate_str(form_data.get("product_code"), max_len=30, required=True)
            sole_model = validate_str(form_data.get("sole_model", ""), max_len=30, required=False) or ""
            upper_model = validate_str(form_data.get("upper_model", ""), max_len=30, required=False) or ""
            sole_source = form_data.get("sole_source")
            upper_source = form_data.get("upper_source")
            # 将 material_id 转为 int 或 None（兼容前端传来的字符串）
            try:
                sole_material_id = int(form_data.get("sole_material_id")) if form_data.get("sole_material_id") else None
            except (ValueError, TypeError):
                sole_material_id = None
            try:
                upper_material_id = int(form_data.get("upper_material_id")) if form_data.get("upper_material_id") else None
            except (ValueError, TypeError):
                upper_material_id = None

        # 序列化其他材料
        other_materials_json = json.dumps(other_materials) if other_materials else None

        # ---- 4. 生成单号 ----
        order_no = OrderDAO.get_next_sequence(conn, order_type)

        # ---- 5. 创建订单记录 ----
        order_id = OrderDAO.create(
            conn=conn,
            order_no=order_no,
            product_code=product_code,
            sole_model=sole_model,
            upper_model=upper_model,
            created_date=created_date,
            status="pending",
            created_by=user_id,
            notes=notes,
            order_type=order_type,
            sole_source=sole_source,
            sole_material_id=sole_material_id,
            upper_source=upper_source,
            upper_material_id=upper_material_id,
            other_materials=other_materials_json,
            direct_sale=direct_sale,
            images=images,
            size_start=size_start,
            size_end=size_end,
        )

        # ---- 6. 创建颜色明细 ----
        for cd in parsed_colors:
            OrderColorDAO.create(conn, order_id, cd["name"], cd["sizes"])

        # ---- 7. 如果是 assembly 类型：从库存扣减材料 ----
        if order_type == "assembly":
            total_quantities = [0] * 6
            for cd in parsed_colors:
                for i in range(6):
                    total_quantities[i] += cd["sizes"][i]

            # 扣减鞋底材料
            if sole_material_id and sole_source not in ("other", None):
                inv = InventoryDAO.get_by_id(conn, sole_material_id)
                if inv:
                    from services.inventory_service import InventoryService

                    InventoryService.consume_inventory(
                        conn=conn,
                        inventory_type=inv["inventory_type"],
                        product_code=inv["product_code"],
                        color=inv["color"],
                        quantities=total_quantities,
                        order_id=order_id,
                        operator_id=user_id,
                        notes="成型领用出库-鞋底",
                    )

            # 扣减帮面材料
            if upper_material_id and upper_source not in ("other", None):
                inv = InventoryDAO.get_by_id(conn, upper_material_id)
                if inv:
                    from services.inventory_service import InventoryService

                    InventoryService.consume_inventory(
                        conn=conn,
                        inventory_type=inv["inventory_type"],
                        product_code=inv["product_code"],
                        color=inv["color"],
                        quantities=total_quantities,
                        order_id=order_id,
                        operator_id=user_id,
                        notes="成型领用出库-帮面",
                    )

            # 扣减其他材料
            for item in other_materials:
                src = item.get("source")
                raw_mat_id = item.get("material_id")
                try:
                    mat_id = int(raw_mat_id) if raw_mat_id else None
                except (ValueError, TypeError):
                    mat_id = None
                if mat_id and src not in ("other", None):
                    inv = InventoryDAO.get_by_id(conn, mat_id)
                    if inv:
                        from services.inventory_service import InventoryService

                        InventoryService.consume_inventory(
                            conn=conn,
                            inventory_type=inv["inventory_type"],
                            product_code=inv["product_code"],
                            color=inv["color"],
                            quantities=total_quantities,
                            order_id=order_id,
                            operator_id=user_id,
                            notes="成型领用出库-其他",
                        )

        # ---- 8. 生成车间任务 ----
        if order_type == "blow":
            blow_task_id = TaskDAO.create(conn, order_id, "blow", total_pairs)
            if not direct_sale:
                TaskDAO.create(conn, order_id, "paint", total_pairs, parent_task_id=blow_task_id)
        elif order_type == "pu":
            pu_task_id = TaskDAO.create(conn, order_id, "pu", total_pairs)
            if not direct_sale:
                TaskDAO.create(conn, order_id, "paint", total_pairs, parent_task_id=pu_task_id)
        elif order_type == "plastic":
            TaskDAO.create(conn, order_id, "plastic", total_pairs)
        elif order_type == "assembly":
            TaskDAO.create(conn, order_id, "assembly", total_pairs)

        logger.info(
            f"指令单创建: order_no={order_no}, type={order_type}, "
            f"total_pairs={total_pairs}, colors={len(parsed_colors)}, "
            f"size_start={size_start}, size_end={size_end}"
        )

        return {"order_no": order_no, "total_pairs": total_pairs}

    @staticmethod
    @transaction
    def list_orders(search: str = None) -> list[dict]:
        conn = get_transaction_conn()
        """列出所有指令单，支持搜索。

        Args:
            conn: 数据库连接（由 @transaction 注入）
            search: 搜索关键词（匹配单号、型号）

        Returns:
            指令单列表
        """
        return OrderDAO.list_all(conn, search=search)

    @staticmethod
    @transaction
    def get_order_detail(order_id: int) -> dict:
        conn = get_transaction_conn()
        """获取订单完整详情（含颜色明细和任务列表）。

        Args:
            conn: 数据库连接（由 @transaction 注入）
            order_id: 指令单 ID

        Returns:
            完整订单详情字典，包含：
                - order: 订单基本信息
                - colors: 颜色明细列表（含 plan 和 completed）
                - tasks: 任务列表

        Raises:
            ResourceNotFound: 指令单不存在
        """
        order = OrderDAO.get_by_id(conn, order_id)
        if not order:
            raise ResourceNotFound("指令单不存在")

        colors = OrderColorDAO.list_by_order(conn, order_id)

        # 查询任务列表
        c = conn.cursor()
        c.execute(
            """SELECT w.name, t.total_boxes, t.completed_boxes, t.status, t.confirmed_at
               FROM prod_tasks t
               JOIN workshops w ON w.code = t.workshop_code
               WHERE t.order_id = ?
               ORDER BY w.sequence, w.name""",
            (order_id,),
        )
        tasks = [
            {
                "name": r["name"],
                "total_boxes": r["total_boxes"],
                "completed_boxes": r["completed_boxes"],
                "status": r["status"],
                "confirmed_at": r["confirmed_at"],
            }
            for r in c.fetchall()
        ]

        return {"order": order, "colors": colors, "tasks": tasks}

    @staticmethod
    @transaction_immediate
    def delete_order(order_id: int, operator_role: str = "") -> bool:
        conn = get_transaction_conn()
        """删除指令单（仅管理员可操作）。

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            order_id: 指令单 ID
            operator_role: 操作人角色

        Returns:
            True 表示删除成功

        Raises:
            PermissionDenied: 非管理员
            ResourceNotFound: 指令单不存在
        """
        if operator_role != "admin":
            raise PermissionDenied("无权限删除指令单")

        order = OrderDAO.get_by_id(conn, order_id)
        if not order:
            raise ResourceNotFound("指令单不存在")

        OrderDAO.delete(conn, order_id)
        logger.info(f"指令单删除: order_id={order_id}, order_no={order['order_no']}")
        return True

    @staticmethod
    @transaction_immediate
    def update_order_status(order_id: int, status: str) -> None:
        conn = get_transaction_conn()
        """更新指令单状态。

        状态流转：
            pending → partial → completed

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            order_id: 指令单 ID
            status: 新状态（pending / partial / completed）

        Raises:
            ValidationError: 状态值无效
        """
        validate_choice(status, ["pending", "partial", "completed"])

        order = OrderDAO.get_by_id(conn, order_id)
        if not order:
            raise ResourceNotFound("指令单不存在")

        OrderDAO.update_status(conn, order_id, status)
        logger.info(f"指令单状态更新: order_id={order_id}, status={status}")
