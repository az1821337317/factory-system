"""业务逻辑层（Service Layer）—— 封装所有核心业务流程。

Service 层是系统的核心，负责协调 DAO 层完成原子性业务操作。
所有 Service 方法通过 @transaction 或 @transaction_immediate 装饰器自动管理事务，
只依赖 DAO 层，不直接操作数据库。

导出：
    - UserService: 用户认证、密码/用户名修改
    - OrderService: 指令单创建、查询、删除
    - TaskService: 任务进度提交、喷漆接收、成型出库
    - InventoryService: 入库、出库、库存转移、查询

使用示例：
    from services import OrderService, TaskService

    # 创建指令单（事务自动管理）
    result = OrderService.create_order(conn=None, form_data={...}, user_id=1)
    # 注意：conn 参数由 @transaction_immediate 装饰器自动注入
"""

from services.inventory_service import InventoryService
from services.order_service import OrderService
from services.task_service import TaskService
from services.user_service import UserService

__all__ = [
    "UserService",
    "OrderService",
    "TaskService",
    "InventoryService",
]
