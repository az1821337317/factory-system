"""任务业务逻辑层 —— 封装任务进度提交、喷漆接收、成型出库等核心业务流程。

本模块包含系统中最复杂的业务逻辑 —— submit_task_progress，
完整实现了原 _process_task_sizes 的所有状态流转规则。
"""

import json
import logging
from datetime import datetime

from models.database import get_transaction_conn, transaction, transaction_immediate
from models.inventory import InventoryDAO
from models.order import OrderColorDAO, OrderDAO
from models.task import TaskDAO
from models.task_receive import TaskReceiveDAO
from models.task_completed import TaskCompletedDAO
from utils.exceptions import BusinessError, PermissionDenied, ResourceNotFound, ValidationError
from utils.validators import validate_choice

logger = logging.getLogger(__name__)

# 车间显示名称映射
_WORKSHOP_NAMES = {
    "blow": "吹气",
    "pu": "PU",
    "plastic": "滴塑",
    "paint": "喷漆",
    "assembly": "成型",
}

# 首道工序车间（生产入库用）
_FIRST_WORKSHOPS = {"blow", "pu", "plastic"}

# 首道工序车间到库存类型的映射
_WORKSHOP_INV_TYPE = {
    "blow": "blow_sole",
    "pu": "pu_sole",
    "plastic": "plastic_upper",
}


class TaskService:
    """任务服务类，处理所有与车间任务相关的业务操作。"""

    # ============================================================
    # 查询类方法
    # ============================================================

    @staticmethod
    @transaction
    def list_workshop_tasks(workshop_code: str, is_admin: bool = False
    ) -> dict:
        conn = get_transaction_conn()

        """获取车间任务列表（含上游状态信息）。

        业务流程：
            1. 查询该车间的待处理任务
            2. 对每个任务查询上游车间状态
            3. 查询已完成任务（最近20条）

        Args:
            conn: 数据库连接（由 @transaction 注入）
            workshop_code: 车间代码
            is_admin: 是否为管理员（影响返回的数据范围）

        Returns:
            {
                "pending": [待处理任务列表],
                "completed": [已完成任务列表],
            }
            每个任务包含 upstream_list 和 upstream_status 字段
        """
        # 待处理任务
        pending_raw = TaskDAO.list_by_workshop(
            conn, workshop_code, include_completed=False
        )

        pending_tasks = []
        for task in pending_raw:
            upstream_list = []
            order_id = task["order_id"]

            # 查询上游任务状态
            if workshop_code == "paint":
                upstream_tasks = TaskDAO.get_upstream_tasks(conn, order_id, "paint")
                for u in upstream_tasks:
                    upstream_list.append(
                        {
                            "code": u["workshop_code"],
                            "completed": u["completed_boxes"],
                            "total": u["total_boxes"],
                        }
                    )
            elif workshop_code == "assembly":
                upstream_tasks = TaskDAO.get_upstream_tasks(conn, order_id, "assembly")
                for u in upstream_tasks:
                    upstream_list.append(
                        {
                            "code": u["workshop_code"],
                            "completed": u["completed_boxes"],
                            "total": u["total_boxes"],
                        }
                    )

            # 构建上游状态显示文本
            upstream_status_parts = []
            for u in upstream_list:
                status_text = (
                    "完成" if u["completed"] >= u["total"] else "进行中"
                )
                name = _WORKSHOP_NAMES.get(u["code"], u["code"])
                upstream_status_parts.append(
                    f"{name}: {u['completed']}/{u['total']} ({status_text})"
                )
            upstream_status = (
                " | ".join(upstream_status_parts)
                if upstream_status_parts
                else None
            )

            pending_tasks.append(
                {
                    "id": task["id"],
                    "order_id": task["order_id"],
                    "order_no": task["order_no"],
                    "product_code": task["product_code"],
                    "sole_model": task["sole_model"],
                    "upper_model": task["upper_model"],
                    "created_date": task["created_date"],
                    "total_boxes": task["total_boxes"],
                    "completed_boxes": task["completed_boxes"],
                    "status": task["status"],
                    "upstream_list": upstream_list,
                    "upstream_status": upstream_status,
                    "received_quantity": task.get("received_quantity", 0),
                    "direct_sale": task.get("direct_sale", False),
                }
            )

        # 已完成任务
        completed_raw = TaskDAO.list_by_workshop(
            conn, workshop_code, include_completed=True
        )
        completed_tasks = [
            {
                "id": t["id"],
                "order_id": t["order_id"],
                "order_no": t["order_no"],
                "product_code": t["product_code"],
                "sole_model": t["sole_model"],
                "upper_model": t["upper_model"],
                "total": t["total_boxes"],
                "completed": t["completed_boxes"],
                "status": t["status"],
                "confirmed_at": t["confirmed_at"],
            }
            for t in completed_raw
        ]

        return {"pending": pending_tasks, "completed": completed_tasks}

    @staticmethod
    @transaction
    def get_task_detail(task_id: int, user=None) -> dict:
        conn = get_transaction_conn()
        """获取任务详情（含颜色明细、上游状态、可处理量）。

        Args:
            conn: 数据库连接
            task_id: 任务 ID
            user: 当前用户对象(用于权限校验，None则跳过)

        Args:
            conn: 数据库连接（由 @transaction 注入）
            task_id: 任务 ID

        Returns:
            {
                "task": 任务基本信息,
                "colors": [颜色明细列表（含plan/completed）],
                "upstream_ready": bool,
                "upstream_info": [上游状态列表],
                "size_start": int,
                "size_end": int,
                "can_process": int or None,
            }

        Raises:
            ResourceNotFound: 任务不存在
        """
        task = TaskDAO.get_by_id(conn, task_id)
        if not task:
            raise ResourceNotFound("任务不存在")

        # 权限校验
        if user is not None:
            role = getattr(user, "role", "")
            workshop = getattr(user, "workshop", "")
            if role != "admin" and workshop != task.get("workshop_code"):
                raise PermissionError("无权限")

        order_id = task["order_id"]
        workshop_code = task["workshop_code"]

        # 查询颜色明细
        colors_raw = OrderColorDAO.list_by_order(conn, order_id)

        # 判断是否为首道工序
        is_first = workshop_code in _FIRST_WORKSHOPS

        # 查询累计接收量（喷漆车间用）
        cumulative_received = {}
        if workshop_code in ("paint", "assembly"):
            cumulative_received = TaskReceiveDAO.get_cumulative_by_task(conn, task_id)

        # 查询本车间的累计完成量（后续工序用）
        self_completed = {}
        if not is_first:
            self_completed = TaskCompletedDAO.get_cumulative_by_task(conn, task_id)

        # 构建颜色数据
        colors_data = []
        for col in colors_raw:
            plan = col["plan"]
            if is_first:
                # 首工序：返回全局 completed（上游产出累加）
                completed = col["completed"]
            else:
                # 后续工序：返回本车间的 completed 量（从 task_completed_records）
                completed = self_completed.get(col["id"], [0, 0, 0, 0, 0, 0])
            color_item = {
                "id": col["id"],
                "name": col["color_name"],
                "plan": plan,
                "completed": completed,
            }
            # 喷漆/成型车间附加累计接收量
            if workshop_code in ("paint", "assembly"):
                recv = cumulative_received.get(col["id"], [0.0] * 6)
                # 转为整数显示
                color_item["received"] = [int(v) for v in recv]
            colors_data.append(color_item)

        # 查询上游状态
        upstream_ready = True
        upstream_info = []

        if workshop_code == "paint":
            upstream_tasks = TaskDAO.get_upstream_tasks(conn, order_id, "paint")
            for u in upstream_tasks:
                ready = u["completed_boxes"] > 0
                upstream_ready = upstream_ready and ready
                upstream_info.append(
                    {
                        "name": _WORKSHOP_NAMES.get(
                            u["workshop_code"], u["workshop_code"]
                        ),
                        "code": u["workshop_code"],
                        "ready": ready,
                        "completed": u["completed_boxes"],
                        "total": u["total_boxes"],
                    }
                )
        elif workshop_code == "assembly":
            upstream_tasks = TaskDAO.get_upstream_tasks(conn, order_id, "assembly")
            for u in upstream_tasks:
                ready = u["completed_boxes"] > 0
                upstream_ready = upstream_ready and ready
                upstream_info.append(
                    {
                        "name": _WORKSHOP_NAMES.get(
                            u["workshop_code"], u["workshop_code"]
                        ),
                        "code": u["workshop_code"],
                        "ready": ready,
                        "completed": u["completed_boxes"],
                        "total": u["total_boxes"],
                    }
                )

        # 计算可处理量
        can_process = None
        if workshop_code == "paint":
            can_process = (task.get("received_quantity", 0) or 0) - (
                task["completed_boxes"] or 0
            )
        elif workshop_code == "assembly":
            # 查询喷漆车间的完成量
            c = conn.cursor()
            c.execute(
                """SELECT completed_boxes FROM prod_tasks
                   WHERE order_id = ? AND workshop_code = 'paint'""",
                (order_id,),
            )
            pt = c.fetchone()
            # 喷漆车间可处理量 = 已接收量 - 本车间已完成量
            rcv_qty = task.get("received_quantity", 0) or 0
            can_process = rcv_qty - (task["completed_boxes"] or 0)

        return {
            "task": task,
            "colors": colors_data,
            "upstream_ready": upstream_ready,
            "upstream_info": upstream_info,
            "size_start": task.get("size_start", 37),
            "size_end": task.get("size_end", 42),
            "can_process": can_process,
            "is_first_workshop": is_first,
        }

    # ============================================================
    # 核心业务方法：任务进度提交
    # ============================================================

    @staticmethod
    @transaction_immediate
    def submit_task_progress(task_id: int, user_id: int,
        user_role: str,
        user_workshop: str,
        colors_data: list,
        mark_all_complete: bool = False,
    ) -> dict:
        conn = get_transaction_conn()
        """提交任务进度（核心！包含完整的状态流转逻辑）。

        业务流程：
            1. 校验任务存在、权限
            2. 上游校验（paint需blow/pu有产出，assembly需paint有产出）
            3. 喷漆额外校验：检查 received_quantity - completed > 0
            4. 处理颜色完成数据：
               - mark_all_complete=True：将剩余量全部标记为完成
               - mark_all_complete=False：按提交的 colors_data 处理
               - 首工序：累加 completed
               - 后续工序：直接使用 submitted 值（喷漆）
            5. 校验喷漆提交量不超过可处理量
            6. 更新 task.completed_boxes 和 status
            7. 更新订单状态（所有任务完成→completed，部分完成→partial）
            8. 首道工序生产入库（blow→blow_sole, pu→pu_sole, plastic→plastic_upper）

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            task_id: 任务 ID
            user_id: 操作人 ID
            user_role: 操作人角色
            user_workshop: 操作人所属车间
            colors_data: 颜色完成数据列表
                [{"id": color_id, "completed": [0,0,0,0,0,0]}, ...]
            mark_all_complete: True 时将剩余量全部标记为完成

        Returns:
            {"success": True, "task_completed": bool, "completed": int}

        Raises:
            ResourceNotFound: 任务不存在
            PermissionDenied: 无权操作该任务
            BusinessError: 上游未就绪、库存不足等业务规则违反
            ValidationError: 数据格式错误
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ---- 1. 校验任务存在 ----
        task = TaskDAO.get_by_id(conn, task_id)
        if not task:
            raise ResourceNotFound("任务不存在")

        # ---- 2. 权限校验 ----
        workshop_code = task["workshop_code"]
        if user_role != "admin" and user_workshop != workshop_code:
            raise PermissionDenied("无权限操作该任务")

        order_id = task["order_id"]
        total_boxes = task["total_boxes"]
        old_completed_boxes = task["completed_boxes"] or 0

        # ---- 3. 上游校验 ----
        if workshop_code == "paint":
            upstream_tasks = TaskDAO.get_upstream_tasks(conn, order_id, "paint")
            if not upstream_tasks or upstream_tasks[0]["completed_boxes"] <= 0:
                raise BusinessError("上游车间尚未有产出")

            # 喷漆额外校验：已接收量必须大于已完成量（普通提交时）
            if not mark_all_complete:
                available = (task.get("received_quantity", 0) or 0) - old_completed_boxes
                if available <= 0:
                    raise BusinessError("请先接收上游鞋底后再提交")

        elif workshop_code == "assembly":
            c = conn.cursor()
            c.execute(
                """SELECT completed_boxes FROM prod_tasks
                   WHERE order_id = ? AND workshop_code = 'paint'""",
                (order_id,),
            )
            paint_task = c.fetchone()
            if not paint_task or paint_task["completed_boxes"] <= 0:
                raise BusinessError("喷漆车间尚未有产出")

        # ---- 4. 获取所有颜色数据 ----
        all_colors = OrderColorDAO.list_by_order(conn, order_id)
        if not all_colors:
            raise BusinessError("订单颜色数据缺失")

        color_map = {col["id"]: col for col in all_colors}
        old_completed_map = {}  # 记录旧 completed 值用于计算增量
        is_first = workshop_code in _FIRST_WORKSHOPS
        submitted_total = 0

        # ---- 5. 处理颜色完成数据 ----
        # 与原始系统设计保持一致：
        #   - 只有首工序(blow/pu/plastic)更新 prod_order_colors.completed（累加）
        #   - 后续工序(paint/assembly)只更新 task.completed_boxes
        #   - 所有工序的增量计算都用 plan - old_comp
        if mark_all_complete:
            if is_first:
                # 首工序：完成剩余计划量（plan - completed）
                for col in all_colors:
                    plan = col["plan"]
                    old_comp = col["completed"]
                    old_completed_map[col["id"]] = old_comp[:]
                    inc = [plan[i] - old_comp[i] for i in range(6)]
                    if any(x > 0 for x in inc):
                        OrderColorDAO.update_completed(conn, col["id"], inc)
                        submitted_total += sum(inc)
            elif workshop_code == "paint":
                # 喷漆车间：全部完成 = 按码段级别计算 min(plan, received) - self_completed
                self_completed_map = TaskCompletedDAO.get_cumulative_by_task(conn, task_id)
                received_map = TaskReceiveDAO.get_cumulative_by_task(conn, task_id)
                for col in all_colors:
                    plan = col["plan"]
                    sc = self_completed_map.get(col["id"], [0] * 6)
                    rc = received_map.get(col["id"], [0] * 6)
                    # 增量 = min(plan, received) - self_completed（码段级别）
                    inc = [max(0, min(plan[i], int(rc[i])) - int(sc[i])) for i in range(6)]
                    if any(x > 0 for x in inc):
                        TaskCompletedDAO.create(
                            conn, task_id, col["id"], inc, user_id, now, "mark_all_complete"
                        )
                        submitted_total += sum(inc)
            else:
                # 成型车间：完成剩余计划量
                for col in all_colors:
                    plan = col["plan"]
                    old_comp = col["completed"]
                    old_completed_map[col["id"]] = old_comp[:]
                    inc = [plan[i] - old_comp[i] for i in range(6)]
                    if any(x > 0 for x in inc):
                        submitted_total += sum(inc)
        else:
            # 查询本车间累计完成量和已接收量（喷漆车间用）
            self_completed_map = {}
            received_map = {}
            if workshop_code == "paint":
                self_completed_map = TaskCompletedDAO.get_cumulative_by_task(conn, task_id)
                received_map = TaskReceiveDAO.get_cumulative_by_task(conn, task_id)

            for item in colors_data:
                color_id = item.get("id")
                if color_id not in color_map:
                    continue

                col = color_map[color_id]
                submitted = item.get("completed", [])
                if len(submitted) != 6:
                    raise ValidationError(
                        f"颜色 {col['color_name']} 完成数量长度必须为6"
                    )

                plan = col["plan"]
                old_comp = col["completed"]
                old_completed_map[color_id] = old_comp[:]
                color_submitted = 0

                # 喷漆车间：码段级别已接收和已完成
                sc = self_completed_map.get(color_id, [0] * 6) if workshop_code == "paint" else None
                rc = received_map.get(color_id, [0] * 6) if workshop_code == "paint" else None

                for i, val in enumerate(submitted):
                    if val is None or val < 0:
                        raise ValidationError("完成数量无效")
                    if val > plan[i]:
                        raise ValidationError(
                            f"码段{i + 1}完成数量超过计划 {plan[i]}"
                        )

                    # 喷漆车间：码段级别校验，不能超过已接收量 - 本车间已完成量
                    if workshop_code == "paint" and rc and sc:
                        available_seg = int(rc[i]) - int(sc[i])
                        if val > available_seg:
                            raise BusinessError(
                                f"颜色 {col['color_name']} 码段{i + 1} "
                                f"提交{val}双超过可处理量{available_seg}双 "
                                f"(已接收{int(rc[i])} - 本车间已完成{int(sc[i])})"
                            )

                    color_submitted += val

                # 记录本车间完成量（后续工序）
                if color_submitted > 0 and workshop_code in ("paint", "assembly"):
                    TaskCompletedDAO.create(
                        conn, task_id, color_id, submitted, user_id, now, "submit"
                    )

                if is_first:
                    OrderColorDAO.update_completed(conn, color_id, submitted)
                submitted_total += color_submitted

        # ---- 6. 校验喷漆提交量不超过可处理量 ----
        if workshop_code == "paint":
            rcv_qty = task.get("received_quantity", 0) or 0
            available = rcv_qty - old_completed_boxes
            if submitted_total > available:
                raise BusinessError(
                    f"提交{submitted_total}双超过可处理量{available}双 "
                    f"(已接收{rcv_qty} - 本车间已完成{old_completed_boxes})"
                )

        # ---- 7. 计算本车间累计完成量 ----
        actual_completed = old_completed_boxes + submitted_total
        new_status = "completed" if actual_completed >= total_boxes else "pending"

        TaskDAO.update_completed(
            conn, task_id, actual_completed, new_status, user_id, now
        )

        # ---- 8. 更新订单状态 ----
        if new_status == "completed":
            incomplete_count = TaskDAO.count_incomplete_by_order(conn, order_id)
            if incomplete_count == 0:
                OrderDAO.update_status(conn, order_id, "completed")
            else:
                OrderDAO.update_status(conn, order_id, "partial")
        else:
            OrderDAO.update_status(conn, order_id, "partial")

        # ---- 9. 首道工序生产入库 ----
        if is_first and submitted_total > 0:
            inv_type = _WORKSHOP_INV_TYPE[workshop_code]

            # 查询订单的 product_code 和码段范围
            order = OrderDAO.get_by_id(conn, order_id)
            product_code = order["product_code"]
            order_size_start = order.get("size_start", 37) or 37
            order_size_end = order.get("size_end", 42) or 42

            # 重新查询颜色数据（可能已经更新）
            post_colors = OrderColorDAO.list_by_order(conn, order_id)
            for pcol in post_colors:
                new_comp_vals = pcol["completed"]
                old_comp_vals = old_completed_map.get(pcol["id"], [0] * 6)
                inc_array = [new_comp_vals[i] - old_comp_vals[i] for i in range(6)]

                if not any(inc_array):
                    continue

                color_name = pcol["color_name"]

                # 查询或创建库存记录
                inv = InventoryDAO.get_by_type_product_color(
                    conn, inv_type, product_code, color_name
                )
                if inv:
                    # 累加库存
                    InventoryDAO.add_sizes(conn, inv["id"], inc_array)
                    # 更新码段范围
                    c = conn.cursor()
                    c.execute(
                        "UPDATE inventory SET size_start = ?, size_end = ? WHERE id = ?",
                        (order_size_start, order_size_end, inv["id"]),
                    )
                else:
                    # 创建新库存记录
                    InventoryDAO.create(
                        conn,
                        inventory_type=inv_type,
                        product_code=product_code,
                        material_name=product_code,
                        color=color_name,
                        sizes=inc_array,
                        unit="双",
                        size_start=order_size_start,
                        size_end=order_size_end,
                    )

        logger.info(
            f"任务进度提交: task_id={task_id}, workshop={workshop_code}, "
            f"submitted={submitted_total}, total_now={actual_completed}, "
            f"status={new_status}"
        )

        return {
            "success": True,
            "task_completed": new_status == "completed",
            "completed": actual_completed,
        }

    # ============================================================
    # 喷漆接收
    # ============================================================

    @staticmethod
    @transaction_immediate
    def receive_paint_materials(task_id: int,user_id: int,
        user_role: str,
        colors_received: list,
    ) -> dict:
        conn = get_transaction_conn()
        """喷漆接收流程：从源库存扣减 → 入 paint_sole 库存 → 更新接收量。

        业务流程：
            1. 校验任务为喷漆任务
            2. 校验上游是否已完成（有产出）
            3. 确定源库存类型（blow→blow_sole, pu→pu_sole）
            4. 按颜色×码段分别处理：
               a. 查询颜色名称
               b. 查询源库存
               c. 校验并扣减源库存
               d. 入到 paint_sole 库存
               e. 记录出入库日志
            5. 累加更新 task.received_quantity

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            task_id: 任务 ID
            user_id: 操作人 ID
            user_role: 操作人角色
            colors_received: 接收数据列表
                [{"id": color_id, "received": [0,0,0,0,0,0]}, ...]

        Returns:
            {"success": True, "received": int, "total_received": int}

        Raises:
            ResourceNotFound: 任务或库存不存在
            BusinessError: 上游未就绪、库存不足
            ValidationError: 数据格式错误
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. 校验任务
        task = TaskDAO.get_by_id(conn, task_id)
        if not task or task["workshop_code"] != "paint":
            raise ResourceNotFound("喷漆任务不存在")

        order_id = task["order_id"]
        product_code = task["product_code"].strip() if task["product_code"] else ""

        # 2. 校验上游
        c = conn.cursor()
        c.execute(
            """SELECT workshop_code, completed_boxes FROM prod_tasks
               WHERE order_id = ? AND workshop_code IN ('blow', 'pu')""",
            (order_id,),
        )
        upstream = c.fetchone()
        if not upstream:
            raise BusinessError("上游任务不存在")

        # 3. 确定源库存类型
        source_type = "blow_sole" if upstream["workshop_code"] == "blow" else "pu_sole"
        size_start = task.get("size_start", 37) or 37
        size_end = task.get("size_end", 42) or 42

        total_received = 0

        # 4. 按颜色分别处理
        for item in colors_received:
            color_id = item.get("id")
            received_arr = item.get("received", [])
            if len(received_arr) != 6:
                raise ValidationError(f"颜色{color_id}接收数量格式错误，必须为6个码段")

            color_received = sum(received_arr)
            if color_received <= 0:
                continue
            total_received += color_received

            # 查询颜色名称
            all_colors = OrderColorDAO.list_by_order(conn, order_id)
            color_name = None
            for col in all_colors:
                if col["id"] == color_id:
                    color_name = col["color_name"].strip()
                    break

            if color_name is None:
                raise ResourceNotFound(f"颜色ID{color_id}不存在")

            # 查询源库存
            src_inv = InventoryDAO.get_by_type_product_color(
                conn, source_type, product_code, color_name
            )
            if not src_inv:
                raise BusinessError(f"{color_name}源库存不存在")

            # 校验每个码段的可用量
            for i in range(6):
                avail = src_inv["sizes"][i] or 0
                qty = received_arr[i]
                if qty > avail:
                    raise BusinessError(
                        f"{color_name}码段{i + 1}接收{qty}超过可用{avail}"
                    )

            # 扣减源库存
            InventoryDAO.subtract_sizes(conn, src_inv["id"], received_arr)

            # 记录出库日志
            from models.inventory import InventoryLogDAO

            InventoryLogDAO.create(
                conn,
                inventory_id=src_inv["id"],
                action="transfer_out",
                sizes_json=json.dumps(received_arr),
                operator_id=user_id,
                task_id=task_id,
                notes=f"{color_name}转移至喷漆",
            )

            # 入到 paint_sole 库存（查询或创建）
            paint_inv = InventoryDAO.get_by_type_product_color(
                conn, "paint_sole", product_code, color_name
            )
            if paint_inv:
                paint_id = paint_inv["id"]
                InventoryDAO.add_sizes(conn, paint_id, received_arr)
                # 更新码段范围
                c = conn.cursor()
                c.execute(
                    "UPDATE inventory SET size_start = ?, size_end = ? WHERE id = ?",
                    (size_start, size_end, paint_id),
                )
            else:
                paint_id = InventoryDAO.create(
                    conn,
                    inventory_type="paint_sole",
                    product_code=product_code,
                    material_name=product_code,
                    color=color_name,
                    sizes=[0, 0, 0, 0, 0, 0],  # 先创建空记录
                    unit="双",
                    size_start=size_start,
                    size_end=size_end,
                )
                # 再累加
                InventoryDAO.add_sizes(conn, paint_id, received_arr)

            # 记录入库日志
            InventoryLogDAO.create(
                conn,
                inventory_id=paint_id,
                action="transfer_in",
                sizes_json=json.dumps(received_arr),
                operator_id=user_id,
                task_id=task_id,
                notes=f"{color_name}来自吹气/PU",
            )

            # 6. 记录接收明细（按码段追踪）
            TaskReceiveDAO.create(
                conn,
                task_id=task_id,
                color_id=color_id,
                received=received_arr,
                operator_id=user_id,
                received_at=now,
                notes=f"{color_name}从{source_type}接收",
            )

        # 7. 更新任务接收状态（累加）
        old_received = task.get("received_quantity", 0) or 0
        new_received = old_received + total_received
        TaskDAO.update_received(conn, task_id, new_received, now)

        logger.info(
            f"喷漆接收: task_id={task_id}, received={total_received}, "
            f"total={new_received}"
        )

        return {
            "success": True,
            "received": total_received,
            "total_received": new_received,
        }

    # ============================================================
    # 成型出库
    # ============================================================

    @staticmethod
    @transaction_immediate
    def assembly_outbound(task_id: int,user_id: int,
        user_role: str,
        user_workshop: str,
        colors_data: list,
    ) -> dict:
        conn = get_transaction_conn()
        """成型出库流程。

        业务流程：
            1. 校验任务为成型任务
            2. 权限校验（admin 或 assembly 车间）
            3. 如果没有提供 colors_data，自动计算全部完成量
            4. 更新颜色 completed 值（累加模式）
            5. 更新任务和订单状态

        Args:
            conn: 数据库连接（由 @transaction_immediate 注入）
            task_id: 任务 ID
            user_id: 操作人 ID
            user_role: 操作人角色
            user_workshop: 操作人所属车间
            colors_data: 颜色完成数据列表
                [{"id": color_id, "completed": [0,0,0,0,0,0]}, ...]
                为空则自动计算全部完成量

        Returns:
            {"success": True, "added": int, "completed": int}

        Raises:
            ResourceNotFound: 任务不存在
            PermissionDenied: 无权操作
            BusinessError: 业务规则违反
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. 校验任务
        task = TaskDAO.get_by_id(conn, task_id)
        if not task or task["workshop_code"] != "assembly":
            raise ResourceNotFound("成型任务不存在")

        # 2. 权限校验
        if user_role != "admin" and user_workshop != "assembly":
            raise PermissionDenied("无权限操作成型任务")

        order_id = task["order_id"]
        old_completed = task["completed_boxes"] or 0

        # 3. 如果没有提供 colors_data，自动使用所有颜色数据（全部完成）
        if not colors_data:
            all_colors = OrderColorDAO.list_by_order(conn, order_id)
            colors_data = []
            for col in all_colors:
                plan = col["plan"]
                old_comp = col["completed"]
                new_comp = [min(plan[i], max(plan[i], old_comp[i])) for i in range(6)]
                colors_data.append({"id": col["id"], "completed": new_comp})

        # 4. 更新颜色 completed 值
        total_added = 0
        for color in colors_data:
            sizes = color.get("completed", [])
            if len(sizes) == 6:
                total_added += sum(sizes)
                # 成型出库：累加 completed
                OrderColorDAO.update_completed(conn, color["id"], sizes)

        # 5. 更新任务状态
        new_completed = old_completed + total_added
        new_status = "completed" if new_completed >= task["total_boxes"] else "partial"

        TaskDAO.update_completed(
            conn, task_id, new_completed, new_status, user_id, now
        )

        # 更新订单状态
        if new_status == "completed":
            incomplete_count = TaskDAO.count_incomplete_by_order(conn, order_id)
            if incomplete_count == 0:
                OrderDAO.update_status(conn, order_id, "completed")
            else:
                OrderDAO.update_status(conn, order_id, "partial")
        else:
            OrderDAO.update_status(conn, order_id, "partial")

        logger.info(
            f"成型出库: task_id={task_id}, added={total_added}, "
            f"completed={new_completed}, status={new_status}"
        )

        return {
            "success": True,
            "added": total_added,
            "completed": new_completed,
        }

    @staticmethod
    @transaction
    def get_source_colors_for_paint(task_id: int) -> dict:
        conn = get_transaction_conn()
        """获取喷漆任务可用的源库存颜色明细。

        用于前端展示每个颜色×码段的可用量，辅助用户进行接收操作。

        Args:
            conn: 数据库连接（由 @transaction 注入）
            task_id: 喷漆任务 ID

        Returns:
            {
                "source_type": str,
                "upstream_completed": int,
                "product_code": str,
                "size_start": int,
                "size_end": int,
                "colors": [{"id": int, "name": str, "plan": [...], "available": [...]}, ...]
            }

        Raises:
            ResourceNotFound: 任务不存在或非喷漆任务
            BusinessError: 上游不存在
        """
        task = TaskDAO.get_by_id(conn, task_id)
        if not task or task["workshop_code"] != "paint":
            raise ResourceNotFound("喷漆任务不存在")

        order_id = task["order_id"]
        product_code = task["product_code"].strip() if task["product_code"] else ""

        # 查询上游
        c = conn.cursor()
        c.execute(
            """SELECT workshop_code, completed_boxes FROM prod_tasks
               WHERE order_id = ? AND workshop_code IN ('blow', 'pu')""",
            (order_id,),
        )
        upstream = c.fetchone()
        if not upstream:
            raise BusinessError("上游任务不存在")

        source_type = "blow_sole" if upstream["workshop_code"] == "blow" else "pu_sole"

        # 查询订单颜色并匹配源库存
        order_colors = OrderColorDAO.list_by_order(conn, order_id)
        colors_data = []
        for oc in order_colors:
            color_name = oc["color_name"].strip()
            plan = oc["plan"]

            # 查询该颜色在源库存中的可用量
            inv = InventoryDAO.get_by_type_product_color(
                conn, source_type, product_code, color_name
            )
            available = inv["sizes"] if inv else [0, 0, 0, 0, 0, 0]

            colors_data.append(
                {
                    "id": oc["id"],
                    "name": color_name,
                    "plan": plan,
                    "available": [a or 0 for a in available],
                }
            )

        return {
            "source_type": source_type,
            "upstream_completed": upstream["completed_boxes"] or 0,
            "product_code": product_code,
            "size_start": task.get("size_start", 37) or 37,
            "size_end": task.get("size_end", 42) or 42,
            "colors": colors_data,
        }
