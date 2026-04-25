# ============================================
# PythonAnywhere 上线部署教程
# ============================================
# 适用对象: 已将项目代码复制到本地的开发者
# 目标平台: PythonAnywhere (免费版可用)
# ============================================


## 一、注册 PythonAnywhere 账号

1. 访问 https://www.pythonanywhere.com/
2. 点击 "Start running Python online in less than a minute"
3. 填写用户名、邮箱、密码，点击 "Create account"
4. 登录邮箱，点击验证链接激活账号

注意: 免费版限制
- Web 应用每天可访问时间有限（休眠机制）
- 数据库为 SQLite（免费版不支持 MySQL/PostgreSQL）
- 文件存储空间有限


## 二、上传项目代码到 PythonAnywhere

### 方式一：通过 Web 上传（推荐，最简单）

1. 登录 PythonAnywhere 后，点击顶部菜单 "Files"
2. 在文件浏览器中，点击 "Upload a file" 按钮
3. 将本地项目文件逐个上传到 `/home/你的用户名/` 目录
   - 建议先在本地将整个项目打包为 ZIP:
     ```bash
     # 在本地终端执行
     cd /你的项目路径
     zip -r shoe_factory.zip . -x "*.pyc" -x "__pycache__/*" -x "production.db"
     ```
   - 然后在 PythonAnywhere Files 页面上传 ZIP 文件
   - 在 PythonAnywhere 的 Bash Console 中解压:
     ```bash
     cd /home/你的用户名/
     unzip shoe_factory.zip -d shoe_factory/
     ```

### 方式二：通过 Git 克隆（如果你在用 Git）

1. 在 PythonAnywhere 顶部菜单点击 "Consoles" → "Bash"
2. 执行:
   ```bash
   cd /home/你的用户名/
   git clone https://github.com/你的用户名/你的仓库.git shoe_factory
   ```


## 三、创建虚拟环境并安装依赖

1. 打开 Bash Console（Consoles → Bash）
2. 执行以下命令:

```bash
cd /home/你的用户名/shoe_factory

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 验证安装
pip list
```

如果 pip install 慢，可以换源:
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```


## 四、创建 WSGI 配置文件

这是最关键的一步！

1. 点击顶部菜单 "Web"
2. 点击 "Add a new web app"
3. 选择 "Manual configuration (including virtualenvs)"
4. 选择 Python 3.12（或你本地使用的版本）
5. 创建完成后，进入 Web app 配置页面

### 修改 WSGI 配置文件

在 Web 配置页面，找到 "Code" 区域下的 "WSGI configuration file" 链接:
- 点击链接 `/var/www/你的用户名_pythonanywhere_com_wsgi.py`
- 将文件内容**全部替换**为以下内容:

```python
import sys
import os

# 添加项目路径到 Python 路径
path = '/home/你的用户名/shoe_factory'
if path not in sys.path:
    sys.path.insert(0, path)

# 设置工作目录
os.chdir(path)

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv(os.path.join(path, '.env'))

# 导入 Flask 应用
from app import app as application
```

**注意**: 将上面代码中的 `你的用户名` 替换为你的实际用户名！


## 五、配置虚拟环境路径

在 Web 配置页面:

1. 找到 "Virtualenv" 区域
2. 在 "Virtualenv" 输入框中填写:
   ```
   /home/你的用户名/shoe_factory/venv
   ```
3. 点击绿色按钮保存


## 六、配置静态文件（可选但推荐）

在 Web 配置页面:

1. 找到 "Static files" 区域
2. 点击 "Add a new static file mapping"
3. URL: `/static/`
   Directory: `/home/你的用户名/shoe_factory/static`
4. 点击保存


## 七、初始化数据库

1. 打开 Bash Console
2. 执行:

```bash
cd /home/你的用户名/shoe_factory
source venv/bin/activate

# 初始化数据库（创建表、默认数据）
python -c "from models import init_db; init_db()"

# 验证数据库已创建
ls -la production.db
```


## 八、设置环境变量（.env）

1. 在 Files 页面，找到 `/home/你的用户名/shoe_factory/.env`
2. 点击编辑，确保包含以下内容:

```
SECRET_KEY=your-random-secret-key-here-change-this-in-production
ADMIN_PASSWORD=你的强密码
DEMO_PASSWORD=demo123456
```

**重要**: 
- SECRET_KEY 必须修改为一个随机长字符串！
- ADMIN_PASSWORD 必须设置，否则启动报错！
- 不要在代码仓库中提交 .env 文件（已添加到 .gitignore）


## 九、重启 Web 应用

1. 在 Web 配置页面顶部，点击绿色大按钮 **"Reload 你的用户名.pythonanywhere.com"**
2. 等待几秒钟
3. 访问 `https://你的用户名.pythonanywhere.com`
4. 如果看到登录页面，说明部署成功！


## 十、常见问题排查

### 问题1: 访问网站显示 "Something went wrong :- ("

解决步骤:
1. 点击 Web 配置页面的 "Error log" 链接
2. 查看最近的错误信息
3. 常见问题:
   - "ImportError: No module named 'flask'" → 虚拟环境未配置正确
   - "RuntimeError: 请设置环境变量 ADMIN_PASSWORD" → .env 文件未配置
   - "ModuleNotFoundError" → 依赖未安装，重新执行 pip install

### 问题2: CSS/JS/图片加载不出来（404）

解决:
1. 检查静态文件配置是否正确（第6步）
2. 确保 static 目录下有 uploads/orders/ 子目录
3. 创建目录:
   ```bash
   mkdir -p /home/你的用户名/shoe_factory/static/uploads/orders
   ```

### 问题3: 数据库文件权限错误

解决:
```bash
cd /home/你的用户名/shoe_factory
chmod 644 production.db
```

### 问题4: 网站休眠后第一次访问慢

这是免费版的正常限制。休眠后首次访问需要几秒钟唤醒。
可以通过设置 uptime 监控服务定期 ping 来保持唤醒（不推荐，可能违反服务条款）。

### 问题5: 中文显示乱码

解决:
1. 确保所有 .py 文件顶部有 `# -*- coding: utf-8 -*-*`
2. 确保 .env 文件是 UTF-8 编码
3. 确保模板中的中文字符正常


## 十一、后续维护

### 更新代码
1. 在本地修改代码
2. 打包上传并解压覆盖
3. 在 Web 配置页面点击 "Reload" 重启

### 查看日志
- Error log: `/var/log/你的用户名.pythonanywhere.com.error.log`
- Access log: `/var/log/你的用户名.pythonanywhere.com.access.log`
- 在 Web 配置页面点击对应链接查看

### 备份数据库
```bash
cd /home/你的用户名/shoe_factory
cp production.db production.db.backup.$(date +%Y%m%d)
```

### 升级 PythonAnywhere 付费版
如果免费版不够用:
1. 点击顶部 "Account"
2. 选择 "Upgrade" 套餐
3. 付费后获得更多 CPU 时间、存储空间和自定义域名支持


## 十二、安全建议

1. **修改 SECRET_KEY**: 部署前必须将 .env 中的 SECRET_KEY 改为随机长字符串
2. **设置强密码**: ADMIN_PASSWORD 至少8位，包含字母+数字
3. **不要提交 .env**: 确保 .env 在 .gitignore 中
4. **定期备份**: 使用 PythonAnywhere 的 "Files" → "Download" 定期下载 production.db 备份
5. **HTTPS**: PythonAnywhere 免费版已自动启用 HTTPS，无需额外配置


## 十三、快速检查清单

部署完成后，逐一检查:
- [ ] 访问 https://你的用户名.pythonanywhere.com 显示登录页
- [ ] 用 admin / 你的密码 可以登录
- [ ] 可以创建指令单
- [ ] 可以进入库存页面
- [ ] 可以批量入库（下载模板+上传文件）
- [ ] 工人账号可以登录并查看任务
- [ ] 图片上传功能正常

如有问题，查看 Error log 排查！


## 十四、联系方式

PythonAnywhere 官方文档: https://help.pythonanywhere.com/
社区论坛: https://www.pythonanywhere.com/forums/
