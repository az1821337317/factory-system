"""库存业务逻辑层 —— 封装入库、出库、库存转移、查询等库存管理业务流程。"""

import json
import logging

from models.database import get_transaction_conn, transaction, transaction_immediate
from models.inventory import InventoryDAO, InventoryLogDAO
from utils.exceptions import BusinessError, PermissionDenied, ResourceNotFound

logger = logging.getLogger(__name__)

# 允许的库存类型白名单
_ALLOWED_INV_TYPES = {
    "blow_sole",
    "pu_sole",
    "paint_sole",
    "plastic_upper",
    "domestic",
}


class InventoryService:
    """库存服务类，处理所有与库存相关的业务操作。"""

    @staticmethod
    @transaction_immediate
    def batch_inbound(inventory_type: str, items: list[dict], operator_id: int
    ) -> int:
        conn = get_transaction_conn()

        """批量入库/单件入库。

        业务流程：
            1. 校验库存类型合法性
            2. 对每个入库项：
               a. 查询是否已存在相同（类型+型号+颜色）的记录
               b. 存在则累加码段库存
               c. 不存在则新建库存记录
               d. 记录入库日志
            3. 返回入库项数量

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            inventory_type: 库存类型（如 blow_sole, pu_sole 等）
            items: 入库项列表，每项为 dict：
                {
                    "product_code": str,
                    "material_name": str,
                    "color": str,
                    "sizes": [int,int,int,int,int,int],  # 6个码段
                    "unit": str,  # 默认"双"
                    "size_start": int,  # 默认37
                    "size_end": int,    # 默认42
                    "notes": str,
                }
            operator_id: 操作人 ID

        Returns:
            入库项数量

        Raises:
            ValidationError: 库存类型无效
            BusinessError: 库存操作失败
        """
        from utils.validators import validate_choice

        validate_choice(inventory_type, list(_ALLOWED_INV_TYPES))

        count = 0
        for item in items:
            product_code = item.get("product_code", "").strip()
            material_name = item.get("material_name", "").strip()
            color = item.get("color", "").strip()
            sizes = item.get("sizes", [0] * 6)
            unit = item.get("unit", "双") or "双"
            notes = item.get("notes", "")
            size_start = item.get("size_start", 37) or 37
            size_end = item.get("size_end", 42) or 42

            if len(sizes) != 6:
                raise BusinessError(f"码段数量必须为6个: {product_code} {color}")

            # 查询是否已存在
            existing = InventoryDAO.get_by_type_product_color(
                conn, inventory_type, product_code, color
            )

            if existing:
                # 累加现有库存
                inv_id = existing["id"]
                InventoryDAO.add_sizes(conn, inv_id, sizes)
                # 更新码段范围
                c = conn.cursor()
                c.execute(
                    "UPDATE inventory SET size_start = ?, size_end = ? WHERE id = ?",
                    (size_start, size_end, inv_id),
                )
                action = "batch_inbound_existing"
            else:
                # 创建新库存记录
                inv_id = InventoryDAO.create(
                    conn,
                    inventory_type=inventory_type,
                    product_code=product_code,
                    material_name=material_name,
                    color=color,
                    sizes=sizes,
                    unit=unit,
                    size_start=size_start,
                    size_end=size_end,
                )
                action = "batch_inbound_new"

            # 记录入库日志
            InventoryLogDAO.create(
                conn,
                inventory_id=inv_id,
                action=action,
                sizes_json=json.dumps({"sizes": sizes}),
                operator_id=operator_id,
                notes=notes,
            )
            count += 1
            logger.info(
                f"库存入库: action={action}, type={inventory_type}, "
                f"product={product_code}, color={color}, sizes={sizes}"
            )

        logger.info(f"批量入库完成: type={inventory_type}, count={count}")
        return count

    @staticmethod
    @transaction
    def list_inventory(inventory_type: str, search: str = None) -> list[dict]:
        conn = get_transaction_conn()
        """按类型列出库存，支持搜索。

        Args:
            conn: 数据库连接（由 @transaction 注入）
            inventory_type: 库存类型
            search: 搜索关键词（匹配型号、材料名、颜色）

        Returns:
            库存记录列表，每条记录包含格式化后的 size_items 和 total
        """
        rows = InventoryDAO.list_by_type(conn, inventory_type, search=search)
        result = []
        for row in rows:
            quantities = row["sizes"]
            size_items = []
            total = 0
            for i, qty in enumerate(quantities):
                if qty and qty > 0:
                    formatted = f"{qty:g}" if qty != int(qty) else str(int(qty))
                    size_items.append((str(i + 1), formatted))
                    total += qty
            result.append(
                {
                    "id": row["id"],
                    "product_code": row["product_code"],
                    "material_name": row["material_name"],
                    "color": row["color"],
                    "size_items": size_items,
                    "total": total,
                    "unit": row["unit"],
                    "updated_at": row["updated_at"],
                    "notes": row["notes"],
                    "size_start": row["size_start"],
                    "size_end": row["size_end"],
                }
            )
        return result

    @staticmethod
    @transaction_immediate
    def update_inventory_info(inv_id: int, product_code: str,
        material_name: str,
        color: str,
        notes: str,
        size_start: int,
        size_end: int,
    ) -> None:
        conn = get_transaction_conn()
        """更新库存记录的非数量字段。
            inv_id: 库存记录 ID
            product_code: 产品型号
            material_name: 材料名称
            color: 颜色
            notes: 备注
            size_start: 起始码
            size_end: 结束码

        Raises:
            ResourceNotFound: 库存记录不存在
        """
        inv = InventoryDAO.get_by_id(conn, inv_id)
        if not inv:
            raise ResourceNotFound("库存记录不存在")

        InventoryDAO.update_info(
            conn, inv_id, product_code, material_name, color, notes, size_start, size_end
        )
        logger.info(f"库存信息更新: inv_id={inv_id}, product_code={product_code}")

    @staticmethod
    @transaction_immediate
    def delete_inventory(inv_id: int) -> None:
        conn = get_transaction_conn()
        """删除库存记录（含关联日志）。

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            inv_id: 库存记录 ID

        Raises:
            ResourceNotFound: 库存记录不存在
        """
        inv = InventoryDAO.get_by_id(conn, inv_id)
        if not inv:
            raise ResourceNotFound("库存记录不存在")

        InventoryDAO.delete(conn, inv_id)
        logger.info(f"库存删除: inv_id={inv_id}, product_code={inv['product_code']}")

    @staticmethod
    @transaction
    def search_inventory(q: str = None, inv_type: str = None, color: str = None
    ) -> list[dict]:
        conn = get_transaction_conn()

        """搜索库存记录。

        支持按关键词（匹配型号、材料名）、库存类型、颜色筛选。

        Args:
            conn: 数据库连接（由 @transaction 注入）
            q: 搜索关键词
            inv_type: 库存类型过滤
            color: 颜色过滤

        Returns:
            库存记录列表，每条包含 stock 字典和 total
        """
        c = conn.cursor()
        sql = """SELECT id, inventory_type, product_code, material_name, color,
                        size_1, size_2, size_3, size_4, size_5, size_6,
                        unit, size_start, size_end
                 FROM inventory WHERE 1=1"""
        params = []

        if q:
            sql += " AND (product_code LIKE ? OR material_name LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like])
        if inv_type:
            sql += " AND inventory_type = ?"
            params.append(inv_type)
        if color:
            sql += " AND color LIKE ?"
            params.append(f"%{color}%")

        sql += " ORDER BY product_code LIMIT 50"
        c.execute(sql, params)
        rows = c.fetchall()

        materials = []
        for row in rows:
            quantities = [row[f"size_{i}"] for i in range(1, 7)]
            total_available = sum(q or 0 for q in quantities)
            unit = row["unit"] if row["unit"] else "双"
            stock = {}
            for i, qty in enumerate(quantities):
                if qty and qty > 0:
                    stock[str(i + 1)] = qty
            materials.append(
                {
                    "id": row["id"],
                    "product_code": row["product_code"],
                    "material_name": row["material_name"],
                    "inventory_type": row["inventory_type"],
                    "color": row["color"],
                    "stock": stock,
                    "unit": unit,
                    "total": total_available,
                    "size_start": row["size_start"] or 37,
                    "size_end": row["size_end"] or 42,
                }
            )
        return materials

    @staticmethod
    @transaction_immediate
    def consume_inventory(inventory_type: str, product_code: str,
        color: str,
        quantities: list,
        order_id: int,
        task_id: int = None,
        operator_id: int = None,
        notes: str = "成型领用出库",
    ) -> int:
        conn = get_transaction_conn()
        """库存扣减（用于成型出库时的材料消耗）。

        业务流程：
            1. 查询库存记录
            2. 校验每个码段库存是否充足
            3. 扣减库存（使用 InventoryDAO.subtract_sizes，内置校验）
            4. 记录出库日志

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            inventory_type: 库存类型
            product_code: 产品型号
            color: 颜色
            quantities: 6个码段的扣减数量列表
            order_id: 关联指令单 ID
            task_id: 关联任务 ID（可选）
            operator_id: 操作人 ID（可选）
            notes: 操作备注

        Returns:
            库存记录 ID

        Raises:
            BusinessError: 库存不存在或库存不足
        """
        if len(quantities) != 6:
            raise BusinessError("扣减数量必须为6个码段")

        # 1. 查询库存记录
        inv = InventoryDAO.get_by_type_product_color(
            conn, inventory_type, product_code, color
        )
        if not inv:
            raise BusinessError(f"库存不存在：{inventory_type} {product_code} {color}")

        # 2&3. 校验并扣减库存（DAO 层已做校验）
        InventoryDAO.subtract_sizes(conn, inv["id"], quantities)

        # 4. 记录出库日志
        InventoryLogDAO.create(
            conn,
            inventory_id=inv["id"],
            action="consume_out",
            sizes_json=json.dumps(quantities),
            operator_id=operator_id,
            order_id=order_id,
            task_id=task_id,
            notes=notes,
        )

        logger.info(
            f"库存扣减: type={inventory_type}, product={product_code}, color={color}, "
            f"quantities={quantities}, order_id={order_id}"
        )
        return inv["id"]

    @staticmethod
    @transaction_immediate
    def transfer_inventory(source_type: str,target_type: str,
        product_code: str,
        color: str,
        quantities: list,
        operator_id: int,
        task_id: int,
        notes: str = "",
    ) -> None:
        conn = get_transaction_conn()
        """库存转移（用于喷漆接收：从 blow_sole/pu_sole 转移到 paint_sole）。

        业务流程：
            1. 从源库存扣减指定数量
            2. 入到目标库存（如不存在则创建）
            3. 分别记录出库和入库日志

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            source_type: 源库存类型（如 blow_sole, pu_sole）
            target_type: 目标库存类型（如 paint_sole）
            product_code: 产品型号
            color: 颜色
            quantities: 6个码段的转移数量列表
            operator_id: 操作人 ID
            task_id: 关联任务 ID
            notes: 操作备注

        Raises:
            BusinessError: 源库存不存在或库存不足
        """
        if len(quantities) != 6:
            raise BusinessError("转移数量必须为6个码段")

        total_qty = sum(quantities)
        if total_qty <= 0:
            raise BusinessError("转移数量必须大于0")

        # 1. 从源库存扣减
        src_inv = InventoryDAO.get_by_type_product_color(
            conn, source_type, product_code, color
        )
        if not src_inv:
            raise BusinessError(f"源库存不存在：{source_type} {product_code} {color}")

        InventoryDAO.subtract_sizes(conn, src_inv["id"], quantities)

        # 记录出库日志
        InventoryLogDAO.create(
            conn,
            inventory_id=src_inv["id"],
            action="transfer_out",
            sizes_json=json.dumps(quantities),
            operator_id=operator_id,
            task_id=task_id,
            notes=f"{color}转移至喷漆" if not notes else notes,
        )

        # 2. 入到目标库存（查询或创建）
        tgt_inv = InventoryDAO.get_by_type_product_color(
            conn, target_type, product_code, color
        )
        if tgt_inv:
            tgt_id = tgt_inv["id"]
            InventoryDAO.add_sizes(conn, tgt_id, quantities)
        else:
            tgt_id = InventoryDAO.create(
                conn,
                inventory_type=target_type,
                product_code=product_code,
                material_name=product_code,
                color=color,
                sizes=quantities,
                unit="双",
                size_start=37,
                size_end=42,
            )

        # 记录入库日志
        InventoryLogDAO.create(
            conn,
            inventory_id=tgt_id,
            action="transfer_in",
            sizes_json=json.dumps(quantities),
            operator_id=operator_id,
            task_id=task_id,
            notes=f"{color}来自吹气/PU" if not notes else notes,
        )

        logger.info(
            f"库存转移: {source_type}->{target_type}, product={product_code}, "
            f"color={color}, quantities={quantities}, task_id={task_id}"
        )
