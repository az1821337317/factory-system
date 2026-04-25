"""任务接收记录数据访问层 —— 追踪每个颜色每个码段的接收明细。

这是生产系统的核心追踪功能：
- 喷漆车间接收上游产出时，按码段记录接收数量
- 处理页面可查看每个码段的累计接收量
- 支持追溯每次接收的操作人、时间
"""

import sqlite3
from typing import Optional


class TaskReceiveDAO:
    """任务接收记录 DAO。"""

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        task_id: int,
        color_id: int,
        received: list,
        operator_id: Optional[int] = None,
        received_at: str = "",
        notes: str = "",
    ) -> int:
        """创建接收记录。

        Args:
            conn: 数据库连接
            task_id: 任务 ID
            color_id: 颜色明细 ID
            received: 6 元素列表 [r1, r2, r3, r4, r5, r6]
            operator_id: 操作人 ID
            received_at: 接收时间 ISO 格式
            notes: 备注

        Returns:
            新记录 ID
        """
        c = conn.cursor()
        c.execute(
            """INSERT INTO task_receive_records
               (task_id, color_id, received_1, received_2, received_3,
                received_4, received_5, received_6, operator_id, received_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, color_id, received[0], received[1], received[2],
             received[3], received[4], received[5], operator_id, received_at, notes),
        )
        return c.lastrowid

    @staticmethod
    def get_cumulative_by_task_color(
        conn: sqlite3.Connection, task_id: int, color_id: int
    ) -> list:
        """获取某任务某颜色的累计接收量（按码段汇总）。

        Returns:
            [r1, r2, r3, r4, r5, r6] 累计值
        """
        c = conn.cursor()
        c.execute(
            """SELECT SUM(received_1) as s1, SUM(received_2) as s2,
                      SUM(received_3) as s3, SUM(received_4) as s4,
                      SUM(received_5) as s5, SUM(received_6) as s6
               FROM task_receive_records
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
        """获取某任务所有颜色的累计接收量。

        Returns:
            {color_id: [r1, r2, r3, r4, r5, r6]}
        """
        c = conn.cursor()
        c.execute(
            """SELECT color_id,
                      SUM(received_1) as s1, SUM(received_2) as s2,
                      SUM(received_3) as s3, SUM(received_4) as s4,
                      SUM(received_5) as s5, SUM(received_6) as s6
               FROM task_receive_records
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
        """获取某任务的所有接收记录（用于追溯）。

        Returns:
            接收记录列表，每条包含 color_name 和 operator_name
        """
        c = conn.cursor()
        c.execute(
            """SELECT r.*, c.color_name, u.username as operator_name
               FROM task_receive_records r
               JOIN prod_order_colors c ON r.color_id = c.id
               LEFT JOIN users u ON r.operator_id = u.id
               WHERE r.task_id = ?
               ORDER BY r.received_at DESC""",
            (task_id,),
        )
        rows = c.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["received"] = [
                d.pop("received_1"), d.pop("received_2"), d.pop("received_3"),
                d.pop("received_4"), d.pop("received_5"), d.pop("received_6"),
            ]
            result.append(d)
        return result
