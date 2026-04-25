"""模型层入口 —— 导出所有 DAO 并提供数据库初始化函数。"""

import sqlite3

from werkzeug.security import generate_password_hash

from config import Config

from .database import get_db
from .inventory import InventoryDAO, InventoryLogDAO
from .order import OrderDAO, OrderColorDAO
from .task import TaskDAO
from .task_receive import TaskReceiveDAO
from .task_completed import TaskCompletedDAO
from .user import UserDAO

__all__ = [
    "get_db",
    "UserDAO",
    "OrderDAO",
    "OrderColorDAO",
    "TaskDAO",
    "TaskReceiveDAO",
    "TaskCompletedDAO",
    "InventoryDAO",
    "InventoryLogDAO",
    "init_db",
]


def init_db() -> None:
    """数据库初始化（完全重构，统一使用序号码段）。

    功能：
        1. 创建所有表（IF NOT EXISTS）
        2. 插入默认数据（管理员、车间定义、演示用户）
        3. 兼容旧数据库迁移（ALTER TABLE 添加新字段）
    """
    conn = get_db()
    try:
        c = conn.cursor()

        # ---------- 1. 用户表 ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                workshop TEXT
            )"""
        )

        # 默认管理员账户
        admin_pwd = Config.ADMIN_PASSWORD
        if not admin_pwd:
            raise RuntimeError("请设置环境变量 ADMIN_PASSWORD（强密码）")
        c.execute("SELECT id FROM users WHERE username = 'admin'")
        if not c.fetchone():
            hashed = generate_password_hash(admin_pwd)
            c.execute(
                "INSERT INTO users (username, password, role, workshop) VALUES (?, ?, ?, ?)",
                ("admin", hashed, "admin", None),
            )

        # 演示车间用户
        demo_pwd = Config.DEMO_PASSWORD
        workshop_users = [
            ("blow_worker", demo_pwd, "blow"),
            ("pu_worker", demo_pwd, "pu"),
            ("paint_worker", demo_pwd, "paint"),
            ("plastic_worker", demo_pwd, "plastic"),
            ("assembly_worker", demo_pwd, "assembly"),
        ]
        for username, pwd, workshop in workshop_users:
            c.execute("SELECT id FROM users WHERE username = ?", (username,))
            if not c.fetchone():
                hashed = generate_password_hash(pwd)
                c.execute(
                    """INSERT OR IGNORE INTO users
                       (username, password, role, workshop)
                       VALUES (?, ?, 'worker', ?)""",
                    (username, hashed, workshop),
                )

        # ---------- 2. 车间定义表 ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS workshops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                sequence INTEGER NOT NULL
            )"""
        )
        default_workshops = [
            ("blow", "\u5439\u6c14", 1),    # 吹气
            ("pu", "PU", 1),
            ("paint", "\u55b7\u6f06", 2),     # 喷漆
            ("plastic", "\u6ef4\u5851", 1),   # 滴塑
            ("assembly", "\u6210\u578b", 3),  # 成型
        ]
        for code, name, seq in default_workshops:
            c.execute(
                "INSERT OR IGNORE INTO workshops (code, name, sequence) VALUES (?, ?, ?)",
                (code, name, seq),
            )

        # ---------- 3. 生产指令单主表 ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS prod_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE NOT NULL,
                product_code TEXT NOT NULL,
                sole_model TEXT,
                upper_model TEXT,
                created_date TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                notes TEXT,
                order_type TEXT DEFAULT 'assembly',
                sole_source TEXT,
                sole_material_id INTEGER,
                upper_source TEXT,
                upper_material_id INTEGER,
                other_materials TEXT,
                direct_sale BOOLEAN DEFAULT 0,
                images TEXT,
                size_start INTEGER DEFAULT 37,
                size_end INTEGER DEFAULT 42,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )"""
        )

        # ---------- 4. 颜色明细表（统一 6 个码段） ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS prod_order_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                color_name TEXT NOT NULL,
                size_1 INTEGER DEFAULT 0,
                size_2 INTEGER DEFAULT 0,
                size_3 INTEGER DEFAULT 0,
                size_4 INTEGER DEFAULT 0,
                size_5 INTEGER DEFAULT 0,
                size_6 INTEGER DEFAULT 0,
                completed_1 INTEGER DEFAULT 0,
                completed_2 INTEGER DEFAULT 0,
                completed_3 INTEGER DEFAULT 0,
                completed_4 INTEGER DEFAULT 0,
                completed_5 INTEGER DEFAULT 0,
                completed_6 INTEGER DEFAULT 0,
                FOREIGN KEY (order_id) REFERENCES prod_orders(id) ON DELETE CASCADE
            )"""
        )

        # ---------- 5. 工序任务表 ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS prod_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                workshop_code TEXT NOT NULL,
                parent_task_id INTEGER,
                total_boxes INTEGER NOT NULL,
                completed_boxes INTEGER NOT NULL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                confirmed_by INTEGER,
                confirmed_at TEXT,
                received_quantity INTEGER DEFAULT 0,
                received_at TEXT,
                FOREIGN KEY (order_id) REFERENCES prod_orders(id) ON DELETE CASCADE,
                FOREIGN KEY (workshop_code) REFERENCES workshops(code),
                FOREIGN KEY (parent_task_id) REFERENCES prod_tasks(id)
            )"""
        )

        # ---------- 5.5 任务接收记录表（喷漆/成型等工序按码段接收追踪） ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS task_receive_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                received_1 REAL DEFAULT 0,
                received_2 REAL DEFAULT 0,
                received_3 REAL DEFAULT 0,
                received_4 REAL DEFAULT 0,
                received_5 REAL DEFAULT 0,
                received_6 REAL DEFAULT 0,
                operator_id INTEGER,
                received_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (task_id) REFERENCES prod_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (color_id) REFERENCES prod_order_colors(id) ON DELETE CASCADE
            )"""
        )

        # ---------- 5.6 任务完成记录表（各车间按颜色×码段完成追踪） ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS task_completed_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                completed_1 REAL DEFAULT 0,
                completed_2 REAL DEFAULT 0,
                completed_3 REAL DEFAULT 0,
                completed_4 REAL DEFAULT 0,
                completed_5 REAL DEFAULT 0,
                completed_6 REAL DEFAULT 0,
                operator_id INTEGER,
                completed_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (task_id) REFERENCES prod_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (color_id) REFERENCES prod_order_colors(id) ON DELETE CASCADE
            )"""
        )

        # ---------- 6. 库存表（统一 6 个码段） ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inventory_type TEXT NOT NULL,
                product_code TEXT NOT NULL,
                material_name TEXT NOT NULL,
                color TEXT NOT NULL,
                size_1 REAL DEFAULT 0,
                size_2 REAL DEFAULT 0,
                size_3 REAL DEFAULT 0,
                size_4 REAL DEFAULT 0,
                size_5 REAL DEFAULT 0,
                size_6 REAL DEFAULT 0,
                unit TEXT DEFAULT '\u53cc',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                notes TEXT,
                size_start INTEGER DEFAULT 37,
                size_end INTEGER DEFAULT 42,
                UNIQUE(inventory_type, product_code, color)
            )"""
        )

        # ---------- 7. 出入库日志表 ----------
        c.execute(
            """CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inventory_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                sizes_json TEXT NOT NULL,
                operator_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                order_id INTEGER,
                task_id INTEGER,
                notes TEXT,
                FOREIGN KEY (inventory_id) REFERENCES inventory(id),
                FOREIGN KEY (operator_id) REFERENCES users(id),
                FOREIGN KEY (order_id) REFERENCES prod_orders(id),
                FOREIGN KEY (task_id) REFERENCES prod_tasks(id)
            )"""
        )

        # ============================================================
        # 兼容旧数据库：字段与表迁移（同步 fix_db.py 的修改）
        # ============================================================

        # 1. prod_order_colors 表添加 completed_1~6 字段
        try:
            c.execute("SELECT completed_1 FROM prod_order_colors LIMIT 0")
        except sqlite3.OperationalError:
            for i in range(1, 7):
                c.execute(
                    f"ALTER TABLE prod_order_colors ADD COLUMN completed_{i} INTEGER DEFAULT 0"
                )

        # 2. inventory 表添加 unit、notes 字段
        for col_name, col_type in [
            ("unit", "TEXT DEFAULT '\u53cc'"),  # 双
            ("notes", "TEXT"),
        ]:
            try:
                c.execute(f"SELECT {col_name} FROM inventory LIMIT 0")
            except sqlite3.OperationalError:
                c.execute(f"ALTER TABLE inventory ADD COLUMN {col_name} {col_type}")

        # 3. prod_orders 表添加来源相关字段
        for col_name, col_type in [
            ("order_type", "TEXT DEFAULT 'assembly'"),
            ("sole_source", "TEXT"),
            ("sole_material_id", "INTEGER"),
            ("upper_source", "TEXT"),
            ("upper_material_id", "INTEGER"),
            ("other_materials", "TEXT"),
            ("direct_sale", "BOOLEAN DEFAULT 0"),
            ("images", "TEXT"),
        ]:
            try:
                c.execute(f"SELECT {col_name} FROM prod_orders LIMIT 0")
            except sqlite3.OperationalError:
                c.execute(f"ALTER TABLE prod_orders ADD COLUMN {col_name} {col_type}")

        # 4. prod_tasks 表添加 parent_task_id、received 等字段
        for col_name, col_type in [
            ("parent_task_id", "INTEGER"),
            ("received_quantity", "INTEGER DEFAULT 0"),
            ("received_at", "TEXT"),
            ("confirmed_by", "INTEGER"),
            ("confirmed_at", "TEXT"),
        ]:
            try:
                c.execute(f"SELECT {col_name} FROM prod_tasks LIMIT 0")
            except sqlite3.OperationalError:
                c.execute(f"ALTER TABLE prod_tasks ADD COLUMN {col_name} {col_type}")

        # 5. 创建库存锁表
        c.execute(
            """CREATE TABLE IF NOT EXISTS inventory_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inventory_id INTEGER NOT NULL,
                locked_1 REAL DEFAULT 0,
                locked_2 REAL DEFAULT 0,
                locked_3 REAL DEFAULT 0,
                locked_4 REAL DEFAULT 0,
                locked_5 REAL DEFAULT 0,
                locked_6 REAL DEFAULT 0,
                order_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (inventory_id) REFERENCES inventory(id)
            )"""
        )

        # 6. inventory 表添加 stock_locked
        try:
            c.execute("SELECT stock_locked FROM inventory LIMIT 0")
        except sqlite3.OperationalError:
            c.execute(
                "ALTER TABLE inventory ADD COLUMN stock_locked TEXT DEFAULT '{}'"
            )

        # 7. prod_orders 表添加 size_start / size_end
        for col_name, col_type in [
            ("size_start", "INTEGER DEFAULT 37"),
            ("size_end", "INTEGER DEFAULT 42"),
        ]:
            try:
                c.execute(f"SELECT {col_name} FROM prod_orders LIMIT 0")
            except sqlite3.OperationalError:
                c.execute(f"ALTER TABLE prod_orders ADD COLUMN {col_name} {col_type}")

        # 8. inventory 表添加 size_start / size_end
        for col_name, col_type in [
            ("size_start", "INTEGER DEFAULT 37"),
            ("size_end", "INTEGER DEFAULT 42"),
        ]:
            try:
                c.execute(f"SELECT {col_name} FROM inventory LIMIT 0")
            except sqlite3.OperationalError:
                c.execute(f"ALTER TABLE inventory ADD COLUMN {col_name} {col_type}")

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
