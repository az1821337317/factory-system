# 鞋厂生产指令系统重构计划

## 目标
将单文件 Flask 应用（app.py ~1950行）重构为多层架构、高稳定性的系统。

## 当前问题诊断
1. **单文件臃肿** - 所有路由+业务逻辑+数据访问混合在 app.py
2. **数据库连接泄漏风险** - 每个路由手动 get_db()/close()，无连接池管理
3. **无分层架构** - 路由、Service、DAO 全部耦合
4. **事务管理不一致** - 有的用 BEGIN IMMEDIATE，有的不用
5. **模板重复** - 每个页面都有 _mobile 版本，维护困难
6. **业务逻辑耦合** - 库存扣减、任务状态流转等核心逻辑和 HTTP 处理混在一起
7. **异常处理不统一** - 各处重复 try/except/rollback 样板代码

## 目标架构

```
project/
├── config.py              # 配置集中管理
├── app.py                 # 应用入口（<100行）
├── extensions.py          # Flask 扩展初始化
├── models/                # 数据访问层（DAO）
│   ├── __init__.py
│   ├── database.py        # 连接池 + 上下文管理 + 事务装饰器
│   ├── user.py            # 用户数据操作
│   ├── order.py           # 订单数据操作
│   ├── inventory.py       # 库存数据操作
│   └── task.py            # 任务数据操作
├── services/              # 业务逻辑层
│   ├── __init__.py
│   ├── order_service.py   # 订单创建、查询、删除
│   ├── inventory_service.py # 库存出入库、查询
│   ├── task_service.py    # 任务处理、状态流转
│   └── user_service.py    # 用户管理、认证
├── routes/                # 路由/控制器层
│   ├── __init__.py
│   ├── auth.py            # 登录/登出
│   ├── order.py           # 订单路由
│   ├── inventory.py       # 库存路由
│   ├── task.py            # 任务路由
│   └── admin.py           # 用户管理
├── utils/                 # 工具层
│   ├── __init__.py
│   ├── validators.py      # 输入验证
│   ├── security.py        # 登录限制、密码
│   ├── exceptions.py      # 自定义异常体系
│   └── response.py        # 统一响应格式
├── templates/             # 模板（响应式统一，删除 _mobile 重复）
│   ├── base.html          # 统一响应式基础模板
│   ├── login.html
│   ├── index.html
│   ├── create_order.html
│   ├── order_detail.html
│   ├── inventory.html
│   ├── workshop_task.html
│   ├── user_management.html
│   └── security_settings.html
└── static/
```

## 重构阶段

### Stage 1 — 基础层建设
- 创建 config.py（环境变量统一管理）
- 创建 utils/exceptions.py（业务异常体系）
- 创建 utils/validators.py（统一输入验证）
- 创建 utils/security.py（登录限制、密码工具）
- 创建 utils/response.py（统一 JSON 响应）
- 创建 models/database.py（连接池 + 上下文管理器 + 事务装饰器）
- 创建 extensions.py（Flask 扩展集中初始化）

### Stage 2 — 数据访问层（models/）
- 将原 app.py 中所有 SQL 查询提取到 DAO 类
- user.py: 用户 CRUD + 密码校验
- order.py: 订单、颜色明细 CRUD
- inventory.py: 库存、库存日志 CRUD
- task.py: 工序任务 CRUD
- 所有 DAO 使用 database.py 提供的 get_db() 和事务装饰器

### Stage 3 — 业务逻辑层（services/）
- order_service.py: 订单创建逻辑（含库存出库、任务生成）
- inventory_service.py: 出入库、批量入库、库存扣减
- task_service.py: 任务完成处理、上游校验、状态流转、喷漆接收
- user_service.py: 用户更新、密码修改

### Stage 4 — 路由层（routes/）
- 将 HTTP 处理逻辑从原 app.py 迁移
- 路由只负责：参数提取 → 调用 Service → 返回响应
- 使用统一的错误处理装饰器
- 保留所有原有 URL 端点不变（向后兼容）

### Stage 5 — 模板统一
- 将 base.html 改为响应式（包含移动端布局）
- 为每个 _mobile.html 合并到主模板中，使用 CSS 媒体查询
- 删除所有 _mobile.html 文件

### Stage 6 — 入口文件与验证
- 编写新的 app.py（<100行，只负责注册蓝图和启动）
- 检查所有导入正确
- 确保 .env 兼容

## 子代理分工

- **基础架构师**: Stage 1 全部文件
- **DAO 工程师**: Stage 2 models/ 全部文件
- **业务逻辑工程师**: Stage 3 services/ 全部文件
- **路由工程师**: Stage 4 routes/ 全部文件
- **模板工程师**: Stage 5 模板统一

执行顺序：
1. 先并行 Stage 1（基础架构师独立完成）
2. Stage 2 依赖 Stage 1，Stage 3 依赖 Stage 2，Stage 4 依赖 Stage 3 —— 串行
3. Stage 5 模板可以和 Stage 2-4 部分并行（因为模板相对独立）
4. Stage 6 在最后
