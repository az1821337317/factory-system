"""任务完成记录数据访问层 —— 追踪每个车间每个颜色每个码段的累计完成量。

这是生产系统的核心追踪功能：
- 每个车间（喷漆、成型等）按颜色×码段记录完成明细
- 处理页面可查看每个码段的累计完成量
- 支持码段级别的提交校验（不能超过已接收量）
"""

import sqlite3
from typing import Optional


class TaskCompletedDAO:
    """任务完成记录 DAO。"""

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        task_id: int,
        color_id: int,
        completed: list,
        operator_id: Optional[int] = None,
        completed_at: str = "",
        notes: str = "",
    ) -> int:
        """创建完成记录。

        Args:
            conn: 数据库连接
            task_id: 任务 ID
            color_id: 颜色明细 ID
            completed: 6 元素列表 [c1, c2, c3, c4, c5, c6]
            operator_id: 操作人 ID
            completed_at: 完成时间 ISO 格式
            notes: 备注

        Returns:
            新记录 ID
        """
        c = conn.cursor()
        c.execute(
            """INSERT INTO task_completed_records
               (task_id, color_id, completed_1, completed_2, completed_3,
                completed_4, completed_5, completed_6, operator_id, completed_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, color_id, completed[0], completed[1], completed[2],
             completed[3], completed[4], completed[5], operator_id, completed_at, notes),
        )
        return c.lastrowid

    @staticmethod
    def get_cumulative_by_task_color(
        conn: sqlite3.Connection, task_id: int, color_id: int
    ) -> list:
        """获取某任务某颜色的累计完成量（按码段汇总）。

        Returns:
            [c1, c2, c3, c4, c5, c6] 累计值
        """
        c = conn.cursor()
        c.execute(
            """SELECT SUM(completed_1) as s1, SUM(completed_2) as s2,
                      SUM(completed_3) as s3, SUM(completed_4) as s4,
                      SUM(completed_5) as s5, SUM(completed_6) as s6
               FROM task_completed_records
               WHERE task_id = ? AND color_id = ?""",
            (task_id, color_id),
        )
        row = c.fetchone()
        if not row:
            return [0.0] * 6
        return [
            (row["s1"] or 0),
            (row["s2"] or 0),
            (row["s3"] or 0),
            (row["s4"] or 0),
            (row["s5"] or 0),
            (row["s6"] or 0),
        ]

    @staticmethod
    def get_cumulative_by_task(
        conn: sqlite3.Connection, task_id: int
    ) -> dict[int, list]:
        """获取某任务所有颜色的累计完成量。

        Returns:
            {color_id: [c1, c2, c3, c4, c5, c6]}
        """
        c = conn.cursor()
        c.execute(
            """SELECT color_id,
                      SUM(completed_1) as s1, SUM(completed_2) as s2,
                      SUM(completed_3) as s3, SUM(completed_4) as s4,
                      SUM(completed_5) as s5, SUM(completed_6) as s6
               FROM task_completed_records
               WHERE task_id = ?
               GROUP BY color_id""",
            (task_id,),
        )
        result = {}
        for row in c.fetchall():
            result[row["color_id"]] = [
                (row["s1"] or 0),
                (row["s2"] or 0),
                (row["s3"] or 0),
                (row["s4"] or 0),
                (row["s5"] or 0),
                (row["s6"] or 0),
            ]
        return result

    @staticmethod
    def list_records_by_task(
        conn: sqlite3.Connection, task_id: int
    ) -> list[dict]:
        """获取某任务的所有完成记录（用于追溯）。

        Returns:
            完成记录列表，每条包含 color_name 和 operator_name
        """
        c = conn.cursor()
        c.execute(
            """SELECT r.*, c.color_name, u.username as operator_name
               FROM task_completed_records r
               JOIN prod_order_colors c ON r.color_id = c.id
               LEFT JOIN users u ON r.operator_id = u.id
               WHERE r.task_id = ?
               ORDER BY r.completed_at DESC""",
            (task_id,),
        )
        rows = c.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["completed"] = [
                d.pop("completed_1"), d.pop("completed_2"), d.pop("completed_3"),
                d.pop("completed_4"), d.pop("completed_5"), d.pop("completed_6"),
            ]
            result.append(d)
        return result
