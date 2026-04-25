"""配置集中管理模块 —— 从环境变量加载所有配置，支持类属性访问"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（向上回溯查找项目根目录中的 .env）
_base_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_base_dir / ".env")


class Config:
    """应用配置类，所有配置项作为类属性，确保类型安全与默认值。"""

    # ---------- Flask 核心安全 ----------
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
    ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")
    DEMO_PASSWORD: str = os.environ.get("DEMO_PASSWORD", "demo123456")

    # ---------- 数据库 ----------
    DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "production.db")

    # ---------- 上传配置 ----------
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "static/uploads/orders")
    ALLOWED_EXTENSIONS: set = {"png", "jpg", "jpeg", "gif", "webp"}

    # ---------- 登录限制 ----------
    MAX_LOGIN_ATTEMPTS: int = int(os.environ.get("MAX_LOGIN_ATTEMPTS", "5"))
    LOCKOUT_TIME_MINUTES: int = int(os.environ.get("LOCKOUT_TIME_MINUTES", "15"))
    LOGIN_ATTEMPTS_MAX_SIZE: int = int(os.environ.get("LOGIN_ATTEMPTS_MAX_SIZE", "10000"))

    @classmethod
    def get_upload_full_path(cls) -> Path:
        """返回上传目录的绝对路径，并确保目录存在。"""
        upload_path = Path(cls.UPLOAD_FOLDER).resolve()
        upload_path.mkdir(parents=True, exist_ok=True)
        return upload_path

    @classmethod
    def check_admin_password(cls) -> None:
        """启动前校验管理员密码是否已配置，未配置则抛出异常。"""
        if not cls.ADMIN_PASSWORD:
            raise RuntimeError(
                "请设置环境变量 ADMIN_PASSWORD（强密码）后再启动服务"
            )
