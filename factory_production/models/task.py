"""工序任务数据访问层 —— 封装 prod_tasks 表操作"""

import sqlite3
from typing import Optional


class TaskDAO:
    """工序任务 DAO。"""

    _SELECT_BASE = """SELECT t.id, t.order_id, t.workshop_code, t.parent_task_id,
        t.total_boxes, t.completed_boxes, t.status,
        t.confirmed_by, t.confirmed_at, t.received_quantity, t.received_at
        FROM prod_tasks t"""

    _SELECT_WITH_ORDER = """SELECT t.id, t.order_id, t.workshop_code, t.parent_task_id,
        t.total_boxes, t.completed_boxes, t.status,
        t.confirmed_by, t.confirmed_at, t.received_quantity, t.received_at,
        po.order_no, po.product_code, po.sole_model, po.upper_model,
        po.created_date, po.direct_sale, po.size_start, po.size_end, po.images
        FROM prod_tasks t
        JOIN prod_orders po ON t.order_id = po.id"""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """将基础任务行转为字典。"""
        return {
            "id": row["id"],
            "order_id": row["order_id"],
            "workshop_code": row["workshop_code"],
            "parent_task_id": row["parent_task_id"],
            "total_boxes": row["total_boxes"],
            "completed_boxes": row["completed_boxes"],
            "status": row["status"],
            "confirmed_by": row["confirmed_by"],
            "confirmed_at": row["confirmed_at"],
            "received_quantity": row["received_quantity"] or 0,
            "received_at": row["received_at"],
        }

    @staticmethod
    def _row_with_order_to_dict(row: sqlite3.Row) -> dict:
        """将关联指令单的任务行转为字典。"""
        return {
            "id": row["id"],
            "order_id": row["order_id"],
            "workshop_code": row["workshop_code"],
            "parent_task_id": row["parent_task_id"],
            "total_boxes": row["total_boxes"],
            "completed_boxes": row["completed_boxes"],
            "status": row["status"],
            "confirmed_by": row["confirmed_by"],
            "confirmed_at": row["confirmed_at"],
            "received_quantity": row["received_quantity"] or 0,
            "received_at": row["received_at"],
            "order_no": row["order_no"],
            "product_code": row["product_code"],
            "sole_model": row["sole_model"],
            "upper_model": row["upper_model"],
            "created_date": row["created_date"],
            "direct_sale": bool(row["direct_sale"]),
            "size_start": row["size_start"] or 37,
            "size_end": row["size_end"] or 42,
            "images": row["images"],
        }

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        order_id: int,
        workshop_code: str,
        total_boxes: int,
        parent_task_id: Optional[int] = None,
    ) -> int:
        """创建工序任务。

        Args:
            conn: 数据库连接
            order_id: 指令单 ID
            workshop_code: 车间代码
            total_boxes: 任务总箱数（双数）
            parent_task_id: 父任务 ID（上游工序关联）

        Returns:
            新任务 ID
        """
        # 防御性校验
        if total_boxes < 0 or total_boxes > 50000:
            raise ValueError(f"任务数量异常: {total_boxes}")
        c = conn.cursor()
        c.execute(
            """INSERT INTO prod_tasks
               (order_id, workshop_code, parent_task_id, total_boxes, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (order_id, workshop_code, parent_task_id, total_boxes),
        )
        return c.lastrowid

    @staticmethod
    def get_by_id(conn: sqlite3.Connection, task_id: int) -> Optional[dict]:
        """通过 ID 查询任务（含指令单信息）。"""
        c = conn.cursor()
        c.execute(
            f"{TaskDAO._SELECT_WITH_ORDER} WHERE t.id = ?",
            (task_id,),
        )
        row = c.fetchone()
        return TaskDAO._row_with_order_to_dict(row) if row else None

    @staticmethod
    def list_by_workshop(
        conn: sqlite3.Connection,
        workshop_code: str,
        include_completed: bool = False,
    ) -> list[dict]:
        """列出指定车间的任务。

        Args:
            conn: 数据库连接
            workshop_code: 车间代码
            include_completed: 是否包含已完成任务

        Returns:
            任务列表
        """
        c = conn.cursor()
        if include_completed:
            c.execute(
                f"""{TaskDAO._SELECT_WITH_ORDER}
                    WHERE t.workshop_code = ? AND t.status = 'completed'
                    ORDER BY t.confirmed_at DESC LIMIT 20""",
                (workshop_code,),
            )
        else:
            c.execute(
                f"""{TaskDAO._SELECT_WITH_ORDER}
                    WHERE t.workshop_code = ? AND t.status != 'completed'
                    ORDER BY po.created_date DESC, t.id""",
                (workshop_code,),
            )
        return [TaskDAO._row_with_order_to_dict(r) for r in c.fetchall()]

    @staticmethod
    def list_by_order(conn: sqlite3.Connection, order_id: int) -> list[dict]:
        """列出某指令单的所有任务。"""
        c = conn.cursor()
        c.execute(
            f"""{TaskDAO._SELECT_WITH_ORDER}
                WHERE t.order_id = ?
                ORDER BY t.id""",
            (order_id,),
        )
        return [TaskDAO._row_with_order_to_dict(r) for r in c.fetchall()]

    @staticmethod
    def update_completed(
        conn: sqlite3.Connection,
        task_id: int,
        completed_boxes: int,
        status: str,
        confirmed_by: int,
        confirmed_at: str,
    ) -> None:
        """更新任务完成信息。"""
        c = conn.cursor()
        c.execute(
            """UPDATE prod_tasks SET
               completed_boxes = ?, status = ?, confirmed_by = ?, confirmed_at = ?
               WHERE id = ?""",
            (completed_boxes, status, confirmed_by, confirmed_at, task_id),
        )

    @staticmethod
    def update_received(
        conn: sqlite3.Connection,
        task_id: int,
        received_quantity: int,
        received_at: str,
    ) -> None:
        """更新任务接收数量。"""
        c = conn.cursor()
        c.execute(
            "UPDATE prod_tasks SET received_quantity = ?, received_at = ? WHERE id = ?",
            (received_quantity, received_at, task_id),
        )

    @staticmethod
    def count_incomplete_by_order(
        conn: sqlite3.Connection, order_id: int
    ) -> int:
        """统计某指令单未完成（非 completed）的任务数量。"""
        c = conn.cursor()
        c.execute(
            """SELECT COUNT(*) as cnt FROM prod_tasks
               WHERE order_id = ? AND status != 'completed'""",
            (order_id,),
        )
        return c.fetchone()["cnt"]

    @staticmethod
    def get_upstream_tasks(
        conn: sqlite3.Connection,
        order_id: int,
        current_workshop: str,
    ) -> list[dict]:
        """获取当前车间的上游任务。

        上游车间映射：
        - paint 的上游是 blow / pu
        - assembly 的上游是 blow / pu / plastic

        Args:
            conn: 数据库连接
            order_id: 指令单 ID
            current_workshop: 当前车间代码

        Returns:
            上游任务列表（每个 dict 包含 workshop_code, completed_boxes, total_boxes）
        """
        upstream_map = {
            "paint": ["blow", "pu"],
            "assembly": ["blow", "pu", "plastic"],
        }
        upstream_codes = upstream_map.get(current_workshop, [])
        if not upstream_codes:
            return []

        placeholders = ",".join("?" * len(upstream_codes))
        c = conn.cursor()
        c.execute(
            f"""SELECT workshop_code, status, completed_boxes, total_boxes
                FROM prod_tasks
                WHERE order_id = ? AND workshop_code IN ({placeholders})""",
            (order_id, *upstream_codes),
        )
        rows = c.fetchall()
        return [
            {
                "workshop_code": r["workshop_code"],
                "status": r["status"],
                "completed_boxes": r["completed_boxes"],
                "total_boxes": r["total_boxes"],
            }
            for r in rows
        ]
