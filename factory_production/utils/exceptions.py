"""自定义业务异常体系 —— 统一异常基类，便于全局错误处理与日志追踪"""


class AppException(Exception):
    """业务异常基类，所有自定义业务异常均应继承此类。
    
    Attributes:
        message: 错误描述文本
        error_code: HTTP 状态码或业务错误码
    """

    def __init__(self, message: str, error_code: int = 500):
        super().__init__(message)
        self.message = message
        self.error_code = error_code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.error_code}, message={self.message!r})"


class ValidationError(AppException):
    """输入验证失败，如参数缺失、格式错误、范围越界等。"""

    def __init__(self, message: str):
        super().__init__(message, error_code=400)


class AuthenticationError(AppException):
    """认证失败，如用户名/密码错误、Token 无效、会话过期等。"""

    def __init__(self, message: str):
        super().__init__(message, error_code=401)


class PermissionDenied(AppException):
    """权限不足，当前用户无权访问目标资源或执行目标操作。"""

    def __init__(self, message: str):
        super().__init__(message, error_code=403)


class ResourceNotFound(AppException):
    """资源不存在，如指令单、任务、库存记录、用户等未找到。"""

    def __init__(self, message: str):
        super().__init__(message, error_code=404)


class BusinessError(AppException):
    """业务规则违反，如库存不足、上游工序未就绪、状态冲突等。
    
    与 ValidationError 的区别：ValidationError 针对输入格式/参数合法性，
    BusinessError 针对业务逻辑层面的约束冲突。
    """

    def __init__(self, message: str, error_code: int = 400):
        super().__init__(message, error_code=error_code)
