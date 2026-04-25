# ============================================
# 鞋厂生产指令系统 —— 项目说明文档
# ============================================
# 版本: 2.0 (多层架构重构版)
# 创建日期: 2026-04-24
# 技术栈: Python + Flask + SQLite + Jinja2
# ============================================

## 一、项目概述

本系统是一个面向鞋厂的生产指令管理系统，支持：
- 指令单创建与管理
- 库存出入库追踪
- 多车间工序流转（吹气 → PU → 喷漆 → 滴塑 → 成型）
- 工人任务处理与进度追踪
- 码段级别数量管理（37~42码共6个码段）


## 二、文件结构说明

### 入口层
app.py              -- 应用入口（30行），只负责组装各层
                    -- 使用 Flask Application Factory 模式
                    -- 注册 Blueprint、初始化扩展、启动服务

### 配置层
config.py           -- 配置集中管理
                    -- SECRET_KEY、数据库路径、上传目录
                    -- 环境变量加载（python-dotenv）
                    -- 管理员密码校验（启动时检查）

### 扩展层
extensions.py       -- Flask 扩展初始化
                    -- login_manager（用户会话管理）
                    -- csrf（CSRF 防护）
                    -- User 模型类（用户认证）
                    -- 全局异常处理器（区分 HTTP 异常和代码异常）
                    -- 端点别名系统（兼容原始模板中的 url_for）

### 数据访问层 (models/)
models/database.py          -- 数据库连接管理
                            -- get_db() 获取 SQLite 连接（WAL 模式）
                            -- @transaction 装饰器（自动事务管理）
                            -- @transaction_immediate 装饰器（写操作）
                            -- Thread-local 连接存储（支持嵌套事务）

models/user.py              -- UserDAO（用户 CRUD）
                            -- get_by_username、get_by_id、create
                            -- update_username、update_password、list_workers

models/order.py             -- OrderDAO + OrderColorDAO（指令单 CRUD）
                            -- create、get_by_id、delete、list_all
                            -- 单号生成逻辑（前缀+日期+序号）

models/inventory.py         -- InventoryDAO + InventoryLogDAO（库存管理）
                            -- 出入库、库存扣减、日志记录
                            -- 字段白名单防止 SQL 注入

models/task.py              -- TaskDAO（任务管理）
                            -- 创建、查询、状态更新
                            -- 上游任务查询（用于喷漆/成型校验）

models/task_receive.py      -- TaskReceiveDAO（接收记录）
                            -- 码段级别接收量追踪
                            -- 每次接收按颜色×码段记录明细

models/task_completed.py    -- TaskCompletedDAO（完成记录）
                            -- 码段级别完成量追踪
                            -- 各车间独立记录完成量

models/__init__.py          -- init_db() 数据库初始化
                            -- 创建所有表结构
                            -- 插入默认车间数据
                            -- 字段兼容性迁移（ALTER TABLE）

### 业务逻辑层 (services/)
services/user_service.py        -- 用户认证、密码修改、用户名修改
                                -- 登录限制器集成
                                -- 权限校验

services/order_service.py       -- 订单创建完整流程
                                -- 验证 → 生成单号 → 创建订单+颜色
                                -- 出库（assembly 类型）
                                -- 生成车间任务（按 order_type）

services/task_service.py        -- 任务处理核心逻辑（最复杂的模块）
                                -- submit_task_progress：进度提交
                                -- receive_paint_materials：喷漆接收
                                -- assembly_outbound：成型出库
                                -- 码段级别校验（喷漆不能超过已接收量）
                                -- 状态流转校验（上游未就绪拒绝）

services/inventory_service.py   -- 库存管理业务
                                -- batch_inbound：批量/单件入库
                                -- update_inventory_info：更新信息
                                -- delete_inventory：删除
                                -- consume_inventory：库存扣减（成型领用）
                                -- transfer_inventory：库存转移（喷漆接收）

### 路由/控制器层 (routes/)
routes/auth.py          -- 登录/登出
                        -- 登录限制（防暴力破解）
                        -- 移动端自动检测

routes/order.py         -- 首页、创建订单、订单详情、删除订单
                        -- 表单解析（color_name[] + size_N_M）
                        -- 移动端适配

routes/inventory.py     -- 库存列表、删除、搜索
                        -- 批量入库（粘贴/文件上传）
                        -- 模板下载（动态码段）
                        -- 图片上传

routes/task.py          -- 车间任务页面
                        -- 任务详情 API
                        -- 进度提交 API
                        -- 喷漆接收 API
                        -- 成型出库 API
                        -- 全部完成 API

routes/admin.py         -- 用户管理（仅管理员）
                        -- 安全设置（密码修改）

### 工具层 (utils/)
utils/exceptions.py     -- 业务异常体系
                        -- AppException（基类）
                        -- ValidationError、PermissionDenied
                        -- ResourceNotFound、BusinessError
                        -- AuthenticationError

utils/validators.py     -- 统一输入验证函数
                        -- validate_str、validate_int、validate_float
                        -- validate_date、validate_choice
                        -- safe_json_load（防止 JSON 注入）

utils/security.py       -- 安全工具
                        -- LoginLimiter（登录限制器，自动清理）
                        -- PasswordHelper（密码哈希/校验）
                        -- allowed_file（文件扩展名校验）

utils/response.py       -- 统一响应格式
                        -- success_response、error_response
                        -- make_json（Flask Response 对象）

### 模板层 (templates/)
templates/base.html                 -- 桌面端基础模板（响应式）
templates/base_mobile.html          -- 移动端基础模板
templates/login.html / login_mobile.html    -- 登录页
templates/index.html / index_mobile.html    -- 首页（指令单列表+搜索）
templates/create_order.html                 -- 创建指令单
templates/order_detail.html                 -- 订单详情
templates/inventory.html / inventory_mobile.html  -- 库存管理
templates/workshop_task.html / workshop_task_mobile.html  -- 车间任务
templates/user_management.html              -- 用户管理
templates/security_settings.html            -- 安全设置

### 静态文件 (static/)
static/uploads/orders/      -- 订单图片上传目录


## 三、核心业务流程

### 1. 创建指令单流程
① 选择类型（blow/pu/plastic/assembly）
② 填写产品信息（货号、颜色、码段数量）
③ 后端：
   - 生成单号（前缀+日期+序号）
   - 创建订单记录
   - 创建颜色明细（prod_order_colors）
   - assembly 类型：从库存扣减鞋底/帮面
   - 生成车间任务（prod_tasks）
   - blow/pu → 同时生成 paint 子任务（非直销）

### 2. 车间任务处理流程
吹气车间（首工序）：
  ① 查看任务 → 输入各码段完成量
  ② 提交 → 累加 completed_boxes → 产出入库（blow_sole）

喷漆车间（后续工序）：
  ① 查看任务 → 先"接收"上游产出（从 blow_sole 扣减 → 入 paint_sole）
  ② 输入各码段完成量（不能超过已接收量）
  ③ 提交 → 码段级别校验 → 记录完成量

成型车间（后续工序）：
  ① 查看任务 → 检查上游 paint 是否完成
  ② 提交完成 → 更新状态

### 3. 库存管理流程
单件入库：
  ① 填写货号、材料、颜色、各码段数量
  ② 提交 → 创建 inventory 记录

批量入库（文件）：
  ① 下载 CSV 模板（动态码段）
  ② 在 Excel 中填数据 → 另存为 CSV
  ③ 上传文件 → 自动解析入库

批量入库（粘贴）：
  ① 设置码段范围（起始码~结束码）
  ② 粘贴 CSV 格式数据
  ③ 提交 → 逐行解析入库


## 四、关键技术点

### 事务管理
所有写入操作使用 @transaction_immediate 装饰器：
- 自动 BEGIN IMMEDIATE（获取写锁）
- 自动 commit / rollback
- 自动关闭连接
- 嵌套调用复用同一连接

### 码段级别追踪
- task_receive_records 表：记录每次接收的码段明细
- task_completed_records 表：记录每次完成的码段明细
- 前端显示：completed / received / plan（完成/已接收/计划）

### 权限隔离
- 工人只能访问自己车间的任务
- 管理员可以访问所有车间
- 跨车间访问返回 403

### 数据格式兼容
- 订单列表返回 sqlite3.Row（支持模板索引访问 order[0]）
- API 返回扁平 JSON（兼容原始前端 JS）


## 五、数据库表结构

users                   -- 用户表（admin/worker）
workshops               -- 车间表（blow/pu/paint/plastic/assembly）
prod_orders             -- 指令单主表
prod_order_colors       -- 颜色明细表（6个码段）
prod_tasks              -- 任务表（各车间任务）
inventory               -- 库存表（统一6个码段）
inventory_logs          -- 库存日志表
task_receive_records    -- 接收记录表（码段级）
task_completed_records  -- 完成记录表（码段级）


## 六、常见问题排查

1. 启动报错 "请设置环境变量 ADMIN_PASSWORD"
   → 编辑 .env 文件，设置 ADMIN_PASSWORD=你的密码

2. 数据库在哪
   → 首次启动自动创建 production.db（SQLite），与 app.py 同目录

3. 如何改数据库路径
   → 在 .env 中设置 DATABASE_PATH=/你的路径/production.db

4. 上传图片保存到哪
   → static/uploads/orders/ 目录

5. 端口被占用
   → 修改 app.py 最后一行的 port=5000 为其他端口


## 七、维护人员必读

### 修改业务逻辑
→ 先修改 services/ 对应的服务文件
→ 不要直接修改 routes/ 或 models/ 中的业务逻辑

### 修改数据库结构
→ 修改 models/__init__.py 中的 init_db()
→ 添加 ALTER TABLE 语句实现兼容迁移
→ 不要删除旧字段，用添加新字段的方式演进

### 修改前端显示
→ 桌面端：修改 templates/xxx.html
→ 移动端：同时修改 templates/xxx_mobile.html
→ 保持两端功能一致

### 新增路由
→ 在 routes/ 对应模块添加 Blueprint 路由
→ 在 routes/__init__.py 注册别名（兼容原始模板 url_for）

## 八、联系信息
项目路径: /mnt/agents/output/
主入口: app.py
配置文件: .env
