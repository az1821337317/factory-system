"""路由层入口 —— 注册所有 Blueprint 并创建 endpoint 别名。

端点别名机制：
    每个 Blueprint 的路由默认 endpoint 为 {bp_name}.{func_name}（如 auth.login）。
    为兼容原 app.py 中 url_for('login') 等调用，注册后自动创建不带前缀的别名
    （如 login → auth.login），使旧端点名称继续可用。
"""


# ---------- Blueprint endpoint 别名映射 ----------
# 格式: {别名: 目标 endpoint}
_ENDPOINT_ALIASES = {
    # auth
    "login": "auth.login",
    "logout": "auth.logout",
    # order
    "index": "order.index",
    "create_order": "order.create_order",
    "order_detail": "order.order_detail",
    "delete_order": "order.delete_order",
    # inventory
    "inventory_list": "inventory.inventory_list",
    "inventory_delete": "inventory.inventory_delete",
    "api_inventory_search": "inventory.api_inventory_search",
    "api_inventory_batch_add": "inventory.api_inventory_batch_add",
    "api_inventory_update": "inventory.api_inventory_update",
    "upload_order_image": "inventory.upload_order_image",
    "api_order_images": "inventory.api_order_images",
    # task
    "workshop_tasks": "task.workshop_tasks",
    "api_task_detail": "task.api_task_detail",
    "api_task_update_sizes": "task.api_task_update_sizes",
    "api_task_complete": "task.api_task_complete",
    "api_task_receive": "task.api_task_receive",
    "api_task_source_colors": "task.api_task_source_colors",
    "api_complete_assembly_with_sizes": "task.api_complete_assembly_with_sizes",
    "api_assembly_outbound": "task.api_assembly_outbound",
    # admin
    "admin_users": "admin.admin_users",
    "admin_update_user": "admin.admin_update_user",
    "security_settings": "admin.security_settings",
}


def register_blueprints(app):
    """注册所有 Blueprint 到 Flask 应用实例。

    Args:
        app: Flask 应用实例
    """
    from .auth import auth_bp
    from .order import order_bp
    from .inventory import inventory_bp
    from .task import task_bp
    from .admin import admin_bp

    # 注册所有 Blueprint
    app.register_blueprint(auth_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(admin_bp)

    # 创建 endpoint 别名，使 url_for('login') 等价于 url_for('auth.login')
    _create_endpoint_aliases(app)


def _create_endpoint_aliases(app):
    """为 Blueprint endpoint 创建不带前缀的全局别名。

    遍历 _ENDPOINT_ALIASES 映射，为每个目标 endpoint 创建别名 endpoint，
    确保原 app.py 中 url_for('login') 等调用继续工作。
    """
    for alias, target in _ENDPOINT_ALIASES.items():
        if target not in app.view_functions:
            continue
        # 检查别名是否已存在
        if alias in [r.endpoint for r in app.url_map.iter_rules()]:
            continue

        view_func = app.view_functions[target]
        # 找到目标 endpoint 对应的第一个 rule，复制其配置
        for rule in list(app.url_map.iter_rules()):
            if rule.endpoint == target:
                methods = [m for m in rule.methods if m not in ("OPTIONS", "HEAD")]
                defaults = dict(rule.defaults) if rule.defaults else None
                app.add_url_rule(
                    str(rule.rule),
                    endpoint=alias,
                    view_func=view_func,
                    methods=methods,
                    defaults=defaults,
                )
                break
