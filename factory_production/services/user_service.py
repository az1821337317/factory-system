"""用户业务逻辑层 —— 封装登录认证、密码修改、用户名修改等用户相关业务流程。"""

import logging

from models.database import get_transaction_conn, transaction
from models.user import UserDAO
from utils.exceptions import AuthenticationError, PermissionDenied, ResourceNotFound, ValidationError
from utils.security import PasswordHelper

logger = logging.getLogger(__name__)


class UserService:
    """用户服务类，处理所有与用户相关的业务操作。"""

    @staticmethod
    @transaction
    def authenticate(username: str, password: str, login_limiter, ip: str) -> dict:
        conn = get_transaction_conn()
        """登录认证，成功返回用户信息（不含密码），失败抛出 AuthenticationError 并记录失败。

        业务流程：
            1. 检查 IP 是否被登录限制器锁定
            2. 查询用户（含密码哈希）
            3. 校验密码
            4. 成功则清除失败记录，返回用户信息
            5. 失败则记录失败次数，抛出 AuthenticationError

        Args:
            conn: 数据库连接（由 @transaction 注入）
            username: 用户名
            password: 明文密码
            login_limiter: 登录限制器类（如 LoginLimiter）
            ip: 客户端 IP 地址

        Returns:
            用户信息字典（不含 password 字段）

        Raises:
            AuthenticationError: 登录被锁定或用户名/密码错误
        """
        # 1. 检查登录限制
        if login_limiter.is_blocked(ip):
            logger.warning(f"登录被锁定: ip={ip}, username={username}")
            raise AuthenticationError("尝试次数过多，请15分钟后再试")

        # 2. 查询用户
        user = UserDAO.get_by_username(conn, username)
        if not user:
            login_limiter.record_fail(ip)
            logger.warning(f"登录失败（用户不存在）: username={username}, ip={ip}")
            raise AuthenticationError("用户名或密码错误")

        # 3. 校验密码
        if not PasswordHelper.verify(password, user["password"]):
            login_limiter.record_fail(ip)
            logger.warning(f"登录失败（密码错误）: username={username}, ip={ip}")
            raise AuthenticationError("用户名或密码错误")

        # 4. 登录成功，清除失败记录
        login_limiter.clear(ip)
        logger.info(f"登录成功: username={username}, role={user['role']}, ip={ip}")

        # 5. 返回用户信息（排除密码）
        return {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "workshop": user["workshop"],
        }

    @staticmethod
    @transaction
    def change_password(user_id: int, old_password: str, new_password: str) -> None:
        conn = get_transaction_conn()
        """修改密码，需要原密码验证。

        业务流程：
            1. 查询用户获取当前密码哈希
            2. 校验原密码
            3. 校验新密码非空
            4. 更新密码哈希

        Args:
            conn: 数据库连接（由 @transaction 注入）
            user_id: 用户 ID
            old_password: 原明文密码
            new_password: 新明文密码

        Raises:
            ResourceNotFound: 用户不存在
            AuthenticationError: 原密码错误
            ValidationError: 新密码为空
        """
        # 1. 查询用户（含密码）
        user = UserDAO.get_by_id(conn, user_id)
        if not user:
            raise ResourceNotFound("用户不存在")

        # 需要重新查询含密码的版本
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            raise ResourceNotFound("用户不存在")

        # 2. 校验原密码
        if not PasswordHelper.verify(old_password, row["password"]):
            logger.warning(f"密码修改失败（原密码错误）: user_id={user_id}")
            raise AuthenticationError("原密码错误")

        # 3. 校验新密码
        if not new_password or not new_password.strip():
            raise ValidationError("新密码不能为空")

        # 4. 更新密码
        new_hash = PasswordHelper.hash(new_password)
        UserDAO.update_password(conn, user_id, new_hash)
        logger.info(f"密码修改成功: user_id={user_id}")

    @staticmethod
    @transaction
    def change_username(user_id: int, new_username: str) -> None:
        conn = get_transaction_conn()
        """修改用户名，检查唯一性。

        业务流程：
            1. 校验新用户名格式
            2. 检查新用户名是否已被其他用户使用
            3. 更新用户名

        Args:
            conn: 数据库连接（由 @transaction 注入）
            user_id: 用户 ID
            new_username: 新用户名

        Raises:
            ValidationError: 用户名格式错误或已被占用
            ResourceNotFound: 用户不存在
        """
        from utils.validators import validate_str

        # 1. 校验格式
        new_username = validate_str(new_username, max_len=30, required=True)

        # 2. 检查唯一性（排除自己）
        if UserDAO.exists_username(conn, new_username, exclude_id=user_id):
            logger.warning(f"用户名修改失败（已存在）: user_id={user_id}, new_username={new_username}")
            raise ValidationError("用户名已存在")

        # 确认用户存在
        user = UserDAO.get_by_id(conn, user_id)
        if not user:
            raise ResourceNotFound("用户不存在")

        # 3. 更新用户名
        UserDAO.update_username(conn, user_id, new_username)
        logger.info(f"用户名修改成功: user_id={user_id}, new_username={new_username}")

    @staticmethod
    @transaction
    def list_workers(conn) -> list[dict]:
        conn = get_transaction_conn()
        """列出所有 worker 角色用户。

        Args:
            conn: 数据库连接（由 @transaction 注入）

        Returns:
            worker 用户列表（不含密码）
        """
        return UserDAO.list_workers(conn)

    @staticmethod
    @transaction
    def admin_update_user(user_id: int, new_username: str, new_password: str = "") -> None:
        conn = get_transaction_conn()
        """管理员更新用户信息（用户名和密码）。

        Args:
            conn: 数据库连接（由 @transaction 注入）
            user_id: 用户 ID
            new_username: 新用户名
            new_password: 新明文密码（为空则不修改密码）

        Raises:
            ValidationError: 用户名已存在
            ResourceNotFound: 用户不存在
        """
        from utils.validators import validate_str

        new_username = validate_str(new_username, max_len=30, required=True)

        if UserDAO.exists_username(conn, new_username, exclude_id=user_id):
            raise ValidationError("用户名已存在")

        user = UserDAO.get_by_id(conn, user_id)
        if not user:
            raise ResourceNotFound("用户不存在")

        if new_password and new_password.strip():
            # 同时更新用户名和密码
            hashed = PasswordHelper.hash(new_password)
            c = conn.cursor()
            c.execute(
                "UPDATE users SET username = ?, password = ? WHERE id = ?",
                (new_username, hashed, user_id),
            )
            logger.info(f"管理员更新用户（含密码）: user_id={user_id}, username={new_username}")
        else:
            # 只更新用户名
            UserDAO.update_username(conn, user_id, new_username)
            logger.info(f"管理员更新用户名: user_id={user_id}, username={new_username}")
