"""数据库连接管理模块 —— 上下文管理器 + 事务装饰器，杜绝连接泄漏"""

import functools
import sqlite3
import threading
from typing import Any, Callable, Optional

from config import Config

# ---------- Thread-local 存储（Flask 同步单线程模型下安全） ----------

_thread_local = threading.local()


def _set_conn(conn: Optional[sqlite3.Connection]) -> None:
    """设置当前线程的事务连接。"""
    _thread_local.conn = conn


def get_transaction_conn() -> sqlite3.Connection:
    """获取当前事务上下文中的数据库连接。

    必须在 @transaction / @transaction_immediate 装饰的方法内部调用。
    嵌套事务时返回外层同一连接，确保原子性。
    """
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        raise RuntimeError("必须在 @transaction 装饰的方法内调用 get_transaction_conn()")
    return conn


# ---------- 连接栈（追踪嵌套层级） ----------


class _ConnectionStack:
    def __init__(self):
        self._stack: list = []

    def push(self, conn: sqlite3.Connection) -> None:
        self._stack.append(conn)

    def pop(self) -> Optional[sqlite3.Connection]:
        return self._stack.pop() if self._stack else None

    def current(self) -> Optional[sqlite3.Connection]:
        return self._stack[-1] if self._stack else None

    def depth(self) -> int:
        return len(self._stack)


_conn_stack = _ConnectionStack()


# ---------- 公共函数 ----------


def get_db() -> sqlite3.Connection:
    """获取 SQLite 数据库连接，启用 WAL 模式与行工厂。"""
    conn = sqlite3.connect(
        Config.DATABASE_PATH,
        timeout=10,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def get_cursor(conn: sqlite3.Connection) -> sqlite3.Cursor:
    return conn.cursor()


# ---------- 事务装饰器 ----------


def _transaction(
    begin_mode: str = "BEGIN",
    func: Optional[Callable] = None,
) -> Callable:
    if func is None:
        return functools.partial(_transaction, begin_mode)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        existing_conn = _conn_stack.current()
        is_nested = existing_conn is not None

        if is_nested:
            conn = existing_conn
        else:
            conn = get_db()
            _conn_stack.push(conn)
            try:
                conn.execute(begin_mode)
            except Exception:
                _conn_stack.pop()
                conn.close()
                raise

        # 设置 thread-local 连接（供 get_transaction_conn() 使用）
        _set_conn(conn)

        try:
            # 如果函数签名包含 conn 参数（DAO 层），注入连接
            import inspect

            sig = inspect.signature(func)
            if "conn" in sig.parameters and "conn" not in kwargs:
                param_names = list(sig.parameters.keys())
                conn_idx = param_names.index("conn")
                if len(args) > conn_idx and isinstance(
                    args[conn_idx], sqlite3.Connection
                ):
                    # conn 已通过位置传入（嵌套 DAO 调用），替换为当前连接
                    args = args[:conn_idx] + (conn,) + args[conn_idx + 1:]
                elif len(args) <= conn_idx:
                    # conn 未传入，通过关键字注入
                    kwargs["conn"] = conn
                # else: len(args) > conn_idx 但不是 Connection —
                # 说明是 @staticmethod 调用，不走参数注入，用 get_transaction_conn()

            result = func(*args, **kwargs)

            if not is_nested:
                conn.commit()
            return result
        except Exception:
            if not is_nested:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if not is_nested:
                _conn_stack.pop()
                _set_conn(None)
                try:
                    conn.close()
                except Exception:
                    pass

    return wrapper


def transaction(func: Optional[Callable] = None) -> Callable:
    """事务装饰器 —— 标准 BEGIN 模式。"""
    return _transaction("BEGIN", func)


def transaction_immediate(func: Optional[Callable] = None) -> Callable:
    """事务装饰器 —— BEGIN IMMEDIATE 模式（获取写锁）。"""
    return _transaction("BEGIN IMMEDIATE", func)


def close_db(e: Optional[Any] = None) -> None:
    """应用关闭时清理连接栈中的残留连接。"""
    while True:
        conn = _conn_stack.pop()
        if conn is None:
            break
        try:
            conn.close()
        except Exception:
            pass
