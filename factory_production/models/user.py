"""用户数据访问层 —— 封装 users 表的所有 CRUD 操作"""

import sqlite3
from typing import Optional


class UserDAO:
    """用户 DAO，负责 users 表的增删改查。"""

    _SELECT_BASE = """SELECT id, username, password, role, workshop FROM users"""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """将 sqlite3.Row 转为字典（排除 password 字段）。"""
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "workshop": row["workshop"],
        }

    @staticmethod
    def _row_with_password(row: sqlite3.Row) -> dict:
        """将 sqlite3.Row 转为字典（包含 password 字段，仅供认证用）。"""
        return {
            "id": row["id"],
            "username": row["username"],
            "password": row["password"],
            "role": row["role"],
            "workshop": row["workshop"],
        }

    @staticmethod
    def get_by_username(conn: sqlite3.Connection, username: str) -> Optional[dict]:
        """通过用户名查询用户（含密码，仅用于登录认证）。

        Args:
            conn: 数据库连接
            username: 用户名

        Returns:
            dict 或 None —— 包含 password 字段
        """
        c = conn.cursor()
        c.execute(
            f"{UserDAO._SELECT_BASE} WHERE username = ?",
            (username,),
        )
        row = c.fetchone()
        return UserDAO._row_with_password(row) if row else None

    @staticmethod
    def get_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
        """通过 ID 查询用户（不含密码）。

        Args:
            conn: 数据库连接
            user_id: 用户 ID

        Returns:
            dict 或 None
        """
        c = conn.cursor()
        c.execute(
            f"{UserDAO._SELECT_BASE} WHERE id = ?",
            (user_id,),
        )
        row = c.fetchone()
        return UserDAO._row_to_dict(row) if row else None

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        username: str,
        password_hash: str,
        role: str,
        workshop: Optional[str] = None,
    ) -> int:
        """创建新用户。

        Args:
            conn: 数据库连接
            username: 用户名
            password_hash: 已哈希的密码
            role: 角色 ('admin' 或 'worker')
            workshop: 所属车间代码，管理员可为 None

        Returns:
            新用户 ID
        """
        c = conn.cursor()
        c.execute(
            """INSERT INTO users (username, password, role, workshop)
               VALUES (?, ?, ?, ?)""",
            (username, password_hash, role, workshop),
        )
        return c.lastrowid

    @staticmethod
    def update_username(conn: sqlite3.Connection, user_id: int, username: str) -> None:
        """更新用户名。

        Args:
            conn: 数据库连接
            user_id: 用户 ID
            username: 新用户名
        """
        c = conn.cursor()
        c.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (username, user_id),
        )

    @staticmethod
    def update_password(
        conn: sqlite3.Connection, user_id: int, password_hash: str
    ) -> None:
        """更新用户密码。

        Args:
            conn: 数据库连接
            user_id: 用户 ID
            password_hash: 已哈希的新密码
        """
        c = conn.cursor()
        c.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (password_hash, user_id),
        )

    @staticmethod
    def list_workers(conn: sqlite3.Connection) -> list[dict]:
        """列出所有 worker 角色用户（不含密码）。

        Args:
            conn: 数据库连接

        Returns:
            worker 列表
        """
        c = conn.cursor()
        c.execute(
            """SELECT id, username, role, workshop FROM users
               WHERE role = 'worker' ORDER BY workshop, username"""
        )
        return [UserDAO._row_to_dict(r) for r in c.fetchall()]

    @staticmethod
    def exists_username(
        conn: sqlite3.Connection, username: str, exclude_id: Optional[int] = None
    ) -> bool:
        """检查用户名是否已存在（可选排除指定用户）。

        Args:
            conn: 数据库连接
            username: 用户名
            exclude_id: 排除的用户 ID（用于更新时检查）

        Returns:
            True 表示已存在
        """
        c = conn.cursor()
        if exclude_id is not None:
            c.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (username, exclude_id),
            )
        else:
            c.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,),
            )
        return c.fetchone() is not None
