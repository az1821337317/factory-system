"""生产指令单数据访问层 —— 封装 prod_orders / prod_order_colors 表操作"""

import json
import sqlite3
from datetime import date, datetime
from typing import Optional

from utils.exceptions import BusinessError

# 单号前缀映射
_ORDER_PREFIX_MAP = {
    "blow": "CHUI",
    "pu": "PU",
    "plastic": "DS",
    "paint": "PENQ",
    "assembly": "CX",
}

_SIZE_FIELDS = [f"size_{i}" for i in range(1, 7)]
_COMPLETED_FIELDS = [f"completed_{i}" for i in range(1, 7)]


class OrderDAO:
    """生产指令单主表 DAO。"""

    _SELECT_BASE = """SELECT id, order_no, product_code, sole_model, upper_model,
        created_date, status, created_by, created_at, notes,
        order_type, sole_source, sole_material_id, upper_source, upper_material_id,
        other_materials, direct_sale, images, size_start, size_end
        FROM prod_orders"""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """将 sqlite3.Row 转为可序列化的字典。"""
        return {
            "id": row["id"],
            "order_no": row["order_no"],
            "product_code": row["product_code"],
            "sole_model": row["sole_model"],
            "upper_model": row["upper_model"],
            "created_date": row["created_date"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "notes": row["notes"],
            "order_type": row["order_type"],
            "sole_source": row["sole_source"],
            "sole_material_id": row["sole_material_id"],
            "upper_source": row["upper_source"],
            "upper_material_id": row["upper_material_id"],
            "other_materials": row["other_materials"],
            "direct_sale": bool(row["direct_sale"]),
            "images": row["images"],
            "size_start": row["size_start"] or 37,
            "size_end": row["size_end"] or 42,
        }

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        order_no: str,
        product_code: str,
        sole_model: str,
        upper_model: str,
        created_date: str,
        status: str,
        created_by: int,
        notes: Optional[str],
        order_type: str,
        sole_source: Optional[str],
        sole_material_id: Optional[int],
        upper_source: Optional[str],
        upper_material_id: Optional[int],
        other_materials: Optional[str],
        direct_sale: bool,
        images: Optional[str],
        size_start: int,
        size_end: int,
    ) -> int:
        """创建生产指令单。

        Returns:
            新指令单 ID
        """
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """INSERT INTO prod_orders
               (order_no, product_code, sole_model, upper_model, created_date,
                status, created_by, created_at, notes, order_type,
                sole_source, sole_material_id, upper_source, upper_material_id,
                other_materials, direct_sale, images, size_start, size_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_no, product_code, sole_model, upper_model, created_date,
                status, created_by, now, notes, order_type,
                sole_source, sole_material_id, upper_source, upper_material_id,
                other_materials, int(direct_sale), images, size_start, size_end,
            ),
        )
        return c.lastrowid

    @staticmethod
    def get_by_id(conn: sqlite3.Connection, order_id: int) -> Optional[dict]:
        """通过 ID 查询指令单。"""
        c = conn.cursor()
        c.execute(
            f"{OrderDAO._SELECT_BASE} WHERE id = ?",
            (order_id,),
        )
        row = c.fetchone()
        return OrderDAO._row_to_dict(row) if row else None

    @staticmethod
    def delete(conn: sqlite3.Connection, order_id: int) -> bool:
        """删除指令单（级联删除颜色和任务）。

        Returns:
            True 表示成功删除，False 表示记录不存在
        """
        c = conn.cursor()
        c.execute("SELECT id FROM prod_orders WHERE id = ?", (order_id,))
        if not c.fetchone():
            return False
        c.execute("DELETE FROM prod_orders WHERE id = ?", (order_id,))
        return True

    @staticmethod
    def list_all(
        conn: sqlite3.Connection, search: Optional[str] = None
    ) -> list[sqlite3.Row]:
        """列出所有指令单，支持搜索。

        返回 sqlite3.Row 列表（支持索引和键两种访问方式），
        兼容前端模板中的 order[0], order[1] 等索引访问。
        """
        c = conn.cursor()
        sql = f"{OrderDAO._SELECT_BASE} WHERE 1=1"
        params = []
        if search:
            sql += """ AND (order_no LIKE ? OR product_code LIKE ?
                        OR sole_model LIKE ? OR upper_model LIKE ?)"""
            like = f"%{search}%"
            params.extend([like, like, like, like])
        sql += " ORDER BY id DESC"
        c.execute(sql, params)
        return c.fetchall()

    @staticmethod
    def update_status(conn: sqlite3.Connection, order_id: int, status: str) -> None:
        """更新指令单状态。"""
        c = conn.cursor()
        c.execute(
            "UPDATE prod_orders SET status = ? WHERE id = ?",
            (status, order_id),
        )

    @staticmethod
    def get_next_sequence(conn: sqlite3.Connection, order_type: str) -> str:
        """生成下一个单号。

        格式：{PREFIX}{YYYYMMDD}N{NNN}，每天从 N001 开始。
        前缀映射：blow→CHUI, pu→PU, plastic→DS, paint→PENQ, assembly→CX

        Args:
            conn: 数据库连接
            order_type: 订单类型

        Returns:
            完整的单号字符串
        """
        today = date.today().strftime("%Y%m%d")
        prefix = _ORDER_PREFIX_MAP.get(order_type, "PO")
        c = conn.cursor()
        c.execute(
            """SELECT order_no FROM prod_orders
               WHERE order_no LIKE ? ORDER BY order_no DESC LIMIT 1""",
            (f"{prefix}{today}N%",),
        )
        row = c.fetchone()
        seq = 1
        if row:
            last_no = row[0]
            try:
                last_seq = int(last_no.split("N")[-1])
                seq = last_seq + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefix}{today}N{seq:03d}"


class OrderColorDAO:
    """指令单颜色明细 DAO。"""

    _SELECT_BASE = """SELECT id, order_id, color_name,
        size_1, size_2, size_3, size_4, size_5, size_6,
        completed_1, completed_2, completed_3, completed_4, completed_5, completed_6
        FROM prod_order_colors"""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """将颜色行转为字典（包含 plan 与 completed 数组）。"""
        return {
            "id": row["id"],
            "order_id": row["order_id"],
            "color_name": row["color_name"],
            "plan": [row[f"size_{i}"] for i in range(1, 7)],
            "completed": [row[f"completed_{i}"] for i in range(1, 7)],
        }

    @staticmethod
    def create(
        conn: sqlite3.Connection, order_id: int, color_name: str, sizes: list
    ) -> int:
        """创建颜色明细记录。

        Args:
            conn: 数据库连接
            order_id: 指令单 ID
            color_name: 颜色名称
            sizes: 6 个码段的数量列表

        Returns:
            新记录 ID
        """
        if len(sizes) != 6:
            raise BusinessError("码段数量必须为 6 个")
        c = conn.cursor()
        c.execute(
            """INSERT INTO prod_order_colors
               (order_id, color_name, size_1, size_2, size_3, size_4, size_5, size_6)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, color_name, *sizes),
        )
        return c.lastrowid

    @staticmethod
    def list_by_order(conn: sqlite3.Connection, order_id: int) -> list[dict]:
        """查询某指令单的所有颜色明细。"""
        c = conn.cursor()
        c.execute(
            f"{OrderColorDAO._SELECT_BASE} WHERE order_id = ? ORDER BY color_name",
            (order_id,),
        )
        return [OrderColorDAO._row_to_dict(r) for r in c.fetchall()]

    @staticmethod
    def update_completed(
        conn: sqlite3.Connection, color_id: int, completed: list
    ) -> None:
        """累加 completed 值（用于首道工序提交）。

        Args:
            conn: 数据库连接
            color_id: 颜色明细 ID
            completed: 6 个码段的增量列表
        """
        if len(completed) != 6:
            raise BusinessError("completed 数组长度必须为 6")
        c = conn.cursor()
        c.execute(
            """UPDATE prod_order_colors SET
               completed_1 = completed_1 + ?,
               completed_2 = completed_2 + ?,
               completed_3 = completed_3 + ?,
               completed_4 = completed_4 + ?,
               completed_5 = completed_5 + ?,
               completed_6 = completed_6 + ?
               WHERE id = ?""",
            (*completed, color_id),
        )

    @staticmethod
    def set_completed(
        conn: sqlite3.Connection, color_id: int, completed: list
    ) -> None:
        """直接设置 completed 值（成型出库用，覆盖而非累加）。

        Args:
            conn: 数据库连接
            color_id: 颜色明细 ID
            completed: 6 个码段的目标值列表
        """
        if len(completed) != 6:
            raise BusinessError("completed 数组长度必须为 6")
        c = conn.cursor()
        c.execute(
            """UPDATE prod_order_colors SET
               completed_1 = ?,
               completed_2 = ?,
               completed_3 = ?,
               completed_4 = ?,
               completed_5 = ?,
               completed_6 = ?
               WHERE id = ?""",
            (*completed, color_id),
        )
