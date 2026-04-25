"""库存数据访问层 —— 封装 inventory / inventory_logs 表操作"""

import json
import sqlite3
from datetime import datetime
from typing import Optional

from utils.exceptions import BusinessError

# 字段白名单 —— 防止非法字段名注入
_SIZE_FIELDS = [f"size_{i}" for i in range(1, 7)]


class InventoryDAO:
    """库存主表 DAO。"""

    _SELECT_BASE = """SELECT id, inventory_type, product_code, material_name, color,
        size_1, size_2, size_3, size_4, size_5, size_6,
        unit, created_at, updated_at, notes, size_start, size_end
        FROM inventory"""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """将库存行转为可序列化字典。"""
        return {
            "id": row["id"],
            "inventory_type": row["inventory_type"],
            "product_code": row["product_code"],
            "material_name": row["material_name"],
            "color": row["color"],
            "sizes": [row[f"size_{i}"] for i in range(1, 7)],
            "unit": row["unit"] if row["unit"] else "双",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "notes": row["notes"],
            "size_start": row["size_start"] or 37,
            "size_end": row["size_end"] or 42,
        }

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        inventory_type: str,
        product_code: str,
        material_name: str,
        color: str,
        sizes: list,
        unit: str,
        size_start: int,
        size_end: int,
    ) -> int:
        """创建库存记录。

        Args:
            conn: 数据库连接
            inventory_type: 库存类型
            product_code: 产品型号
            material_name: 材料名称
            color: 颜色
            sizes: 6 个码段的数量列表
            unit: 单位
            size_start: 起始码
            size_end: 结束码

        Returns:
            新库存记录 ID
        """
        if len(sizes) != 6:
            raise BusinessError("码段数量必须为 6 个")
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """INSERT INTO inventory
               (inventory_type, product_code, material_name, color,
                size_1, size_2, size_3, size_4, size_5, size_6,
                unit, created_at, updated_at, size_start, size_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                inventory_type, product_code, material_name, color,
                *sizes, unit, now, now, size_start, size_end,
            ),
        )
        return c.lastrowid

    @staticmethod
    def get_by_id(conn: sqlite3.Connection, inv_id: int) -> Optional[dict]:
        """通过 ID 查询库存记录。"""
        c = conn.cursor()
        c.execute(
            f"{InventoryDAO._SELECT_BASE} WHERE id = ?",
            (inv_id,),
        )
        row = c.fetchone()
        return InventoryDAO._row_to_dict(row) if row else None

    @staticmethod
    def get_by_type_product_color(
        conn: sqlite3.Connection,
        inv_type: str,
        product_code: str,
        color: str,
    ) -> Optional[dict]:
        """通过类型+型号+颜色查询库存记录。"""
        c = conn.cursor()
        c.execute(
            f"{InventoryDAO._SELECT_BASE}"
            " WHERE inventory_type = ? AND product_code = ? AND color = ?",
            (inv_type, product_code.strip(), color.strip()),
        )
        row = c.fetchone()
        return InventoryDAO._row_to_dict(row) if row else None

    @staticmethod
    def update_sizes(
        conn: sqlite3.Connection,
        inv_id: int,
        sizes: list,
        operator_notes: str = "",
    ) -> None:
        """批量更新 6 个码段的库存值（覆盖模式）。

        Args:
            conn: 数据库连接
            inv_id: 库存记录 ID
            sizes: 6 个码段的新值列表
            operator_notes: 操作备注
        """
        if len(sizes) != 6:
            raise BusinessError("码段数量必须为 6 个")
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """UPDATE inventory SET
               size_1 = ?, size_2 = ?, size_3 = ?,
               size_4 = ?, size_5 = ?, size_6 = ?,
               updated_at = ?
               WHERE id = ?""",
            (*sizes, now, inv_id),
        )

    @staticmethod
    def add_sizes(conn: sqlite3.Connection, inv_id: int, increments: list) -> None:
        """累加库存（入库用）。

        Args:
            conn: 数据库连接
            inv_id: 库存记录 ID
            increments: 6 个码段的增量列表
        """
        if len(increments) != 6:
            raise BusinessError("码段数量必须为 6 个")
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i, qty in enumerate(increments):
            if qty and qty > 0:
                field = _SIZE_FIELDS[i]  # 白名单取字段名
                c.execute(
                    f"UPDATE inventory SET {field} = {field} + ?, updated_at = ? WHERE id = ?",
                    (qty, now, inv_id),
                )

    @staticmethod
    def subtract_sizes(
        conn: sqlite3.Connection, inv_id: int, decrements: list
    ) -> None:
        """扣减库存（出库用），先校验库存是否充足。

        Args:
            conn: 数据库连接
            inv_id: 库存记录 ID
            decrements: 6 个码段的减量列表

        Raises:
            BusinessError: 库存不足时抛出，包含具体码段信息
        """
        if len(decrements) != 6:
            raise BusinessError("码段数量必须为 6 个")
        c = conn.cursor()

        # 先校验每个码段的库存是否充足
        for i, qty in enumerate(decrements):
            if qty <= 0:
                continue
            field = _SIZE_FIELDS[i]
            c.execute(f"SELECT {field} FROM inventory WHERE id = ?", (inv_id,))
            row = c.fetchone()
            if not row:
                raise BusinessError(f"库存记录不存在: ID={inv_id}")
            current = row[0] or 0
            if current < qty:
                raise BusinessError(
                    f"库存不足：码段{i + 1} 需要 {qty}，可用 {current}"
                )

        # 校验通过后执行扣减
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i, qty in enumerate(decrements):
            if qty > 0:
                field = _SIZE_FIELDS[i]
                c.execute(
                    f"UPDATE inventory SET {field} = {field} - ?, updated_at = ? WHERE id = ?",
                    (qty, now, inv_id),
                )

    @staticmethod
    def list_by_type(
        conn: sqlite3.Connection,
        inv_type: str,
        search: Optional[str] = None,
    ) -> list[dict]:
        """按类型列出库存，支持搜索。"""
        c = conn.cursor()
        sql = f"{InventoryDAO._SELECT_BASE} WHERE inventory_type = ?"
        params = [inv_type]
        if search:
            sql += " AND (product_code LIKE ? OR material_name LIKE ? OR color LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])
        sql += " ORDER BY product_code"
        c.execute(sql, params)
        return [InventoryDAO._row_to_dict(r) for r in c.fetchall()]

    @staticmethod
    def delete(conn: sqlite3.Connection, inv_id: int) -> None:
        """删除库存记录（需先删除关联日志）。"""
        c = conn.cursor()
        c.execute("DELETE FROM inventory_logs WHERE inventory_id = ?", (inv_id,))
        c.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))

    @staticmethod
    def update_info(
        conn: sqlite3.Connection,
        inv_id: int,
        product_code: str,
        material_name: str,
        color: str,
        notes: str,
        size_start: int,
        size_end: int,
    ) -> None:
        """更新库存记录的非数量字段。"""
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """UPDATE inventory SET
               product_code = ?, material_name = ?, color = ?, notes = ?,
               updated_at = ?, size_start = ?, size_end = ?
               WHERE id = ?""",
            (product_code, material_name, color, notes, now, size_start, size_end, inv_id),
        )


class InventoryLogDAO:
    """库存日志 DAO。"""

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        inventory_id: int,
        action: str,
        sizes_json: str,
        operator_id: int,
        order_id: Optional[int] = None,
        task_id: Optional[int] = None,
        notes: str = "",
    ) -> int:
        """创建库存操作日志。

        Args:
            conn: 数据库连接
            inventory_id: 库存记录 ID
            action: 操作类型（如 'consume_out', 'batch_inbound', 'transfer_out'）
            sizes_json: 码段变更的 JSON 字符串
            operator_id: 操作人 ID
            order_id: 关联指令单 ID
            task_id: 关联任务 ID
            notes: 备注

        Returns:
            新日志 ID
        """
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """INSERT INTO inventory_logs
               (inventory_id, action, sizes_json, operator_id, timestamp,
                order_id, task_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (inventory_id, action, sizes_json, operator_id, now, order_id, task_id, notes),
        )
        return c.lastrowid
