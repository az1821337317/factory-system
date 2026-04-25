"""安全工具模块 —— 登录限制、密码处理、文件上传白名单"""

from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional

from werkzeug.security import generate_password_hash, check_password_hash

from config import Config


class LoginLimiter:
    """基于内存字典的登录失败限制器，带自动清理机制防止内存泄漏。

    数据结构：{ip: [失败次数, 首次失败时间]}
    """

    _attempts: Dict[str, Tuple[int, datetime]] = {}

    @classmethod
    def is_blocked(cls, ip: str) -> bool:
        """判断指定 IP 是否处于锁定状态。

        若已超过锁定时长，自动清除该 IP 记录并返回 False。
        """
        if ip not in cls._attempts:
            return False
        attempts, first_fail = cls._attempts[ip]
        if attempts >= Config.MAX_LOGIN_ATTEMPTS:
            if datetime.now() - first_fail < timedelta(minutes=Config.LOCKOUT_TIME_MINUTES):
                return True
            # 锁定时间已过，自动清除
            del cls._attempts[ip]
            return False
        return False

    @classmethod
    def record_fail(cls, ip: str) -> None:
        """记录一次登录失败。当存储量超过阈值时自动清理过期记录。"""
        if len(cls._attempts) > Config.LOGIN_ATTEMPTS_MAX_SIZE:
            cls._cleanup()
        now = datetime.now()
        if ip not in cls._attempts:
            cls._attempts[ip] = [1, now]
        else:
            attempts, first_fail = cls._attempts[ip]
            cls._attempts[ip] = [attempts + 1, first_fail]

    @classmethod
    def clear(cls, ip: str) -> None:
        """清除指定 IP 的失败记录（登录成功后调用）。"""
        cls._attempts.pop(ip, None)

    @classmethod
    def _cleanup(cls) -> None:
        """清理过期登录记录，防止内存泄漏。每次最多清理 1000 条。"""
        now = datetime.now()
        lockout = timedelta(minutes=Config.LOCKOUT_TIME_MINUTES)
        expired = [
            ip for ip, (attempts, first_fail) in cls._attempts.items()
            if attempts < Config.MAX_LOGIN_ATTEMPTS or (now - first_fail) >= lockout
        ]
        for ip in expired[:1000]:
            cls._attempts.pop(ip, None)


class PasswordHelper:
    """密码哈希与校验工具，封装 werkzeug.security。"""

    @staticmethod
    def hash(password: str) -> str:
        """对明文密码进行哈希处理。

        Args:
            password: 明文密码

        Returns:
            哈希后的密码字符串
        """
        return generate_password_hash(password)

    @staticmethod
    def verify(password: str, hashed: str) -> bool:
        """校验明文密码是否与哈希值匹配。

        Args:
            password: 明文密码
            hashed: 哈希后的密码字符串

        Returns:
            是否匹配
        """
        return check_password_hash(hashed, password)


def allowed_file(filename: Optional[str]) -> bool:
    """校验文件名是否在允许的后缀白名单中。

    Args:
        filename: 文件名（可为 None）

    Returns:
        是否允许上传
    """
    if not filename or not isinstance(filename, str):
        return False
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in Config.ALLOWED_EXTENSIONS
