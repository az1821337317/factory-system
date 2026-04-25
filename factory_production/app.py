"""生产指令系统主入口 —— 精简版，只负责组装各层。"""
from flask import Flask

from config import Config
from extensions import init_extensions
from models import init_db
from routes import register_blueprints


def create_app(config_class=Config):
    """应用工厂函数。"""
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY

    # 初始化扩展（login_manager, csrf, 错误处理器等）
    init_extensions(app)

    # 注册蓝图
    register_blueprints(app)

    return app


app = create_app()

if __name__ == '__main__':
    Config.check_admin_password()
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)
