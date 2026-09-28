# CardioCrypt

基于 **ECG（心电）/ PPG（光电容积脉搏波）** 生物特征的无密码身份认证系统。通过蓝牙手环或串口设备采集生理信号，提取时序特征后由 **BiLSTM + Attention** 模型推理，配合 **DTW + 余弦相似度** 完成身份比对。

> 本项目为课程实践项目，用于研究与演示生物特征认证的完整链路。

## 功能概览

| 模块 | 说明 |
|---|---|
| 身份注册 | 采集多次信号样本，训练专属个人模型 |
| 身份认证 | 实时采集并比对，输出判定结果与相似度 |
| 数据采集 | 支持 BLE 蓝牙 / 串口 两类设备，带设备扫描与连接向导 |
| 用户仪表盘 | 心率、情绪、告警等级、设备状态与历史趋势 |
| 管理后台 | 注册用户管理、运行时参数（模型 / 验证 / 设备 / 训练）动态配置 |

## 技术栈

**前端**：React 19 · Vite 6 · TypeScript · Tailwind CSS v4 · Framer Motion · React Router 7
**后端**：Python 3.9 · Flask · PyMongo
**算法**：PyTorch (BiLSTM + Attention) · NumPy · SciPy · PyWavelets · fastdtw · scikit-learn
**存储**：MongoDB

## 目录结构

```
.
├── web_auth/              # Web 应用
│   ├── app.py             # Flask 主程序（路由与业务逻辑）
│   ├── spa_adapter.py     # React SPA 适配层（GET→SPA，POST→原逻辑）
│   ├── frontend/          # React 前端源码
│   │   └── src/
│   │       ├── pages/     # 页面
│   │       ├── components/# 组件
│   │       └── lib/       # API 客户端与工具
│   ├── static/            # 静态资源（含前端构建产物 dist/）
│   └── templates/         # 旧版 Jinja2 模板（classic 模式保留）
├── ecgppg_system/         # 信号处理 / 设备 / 模型 / 可视化 核心库
├── model_example/         # 模型封装模块（训练、评估、推理）
└── requirements.txt
```

## 快速开始

> 更详细的启动步骤、页面导览、使用场景与常见问题排查，见 **[使用指南.md](使用指南.md)**。也可直接双击根目录的 `start.bat` 一键启动。

### 1. 环境准备

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

需要本地运行 **MongoDB**（默认 `mongodb://localhost:27017`）。

### 2. 构建前端

```bash
cd web_auth/frontend
npm install
npm run build                  # 产物输出到 ../static/dist/
```

### 3. 启动服务

```bash
python web_auth/app.py         # 默认 http://127.0.0.1:5000
```

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017/ecg_auth_db` | MongoDB 连接串 |
| `ADMIN_USERNAME` | `admin` | 管理后台账号 |
| `ADMIN_PASSWORD` | `admin123` | 管理后台口令 —— **部署前必须修改** |
| `FLASK_SECRET_KEY` | 随机生成 | 会话密钥，多实例部署时应固定 |
| `FLASK_DEBUG` | `0` | 设为 `1` 开启调试模式。**会暴露可执行任意代码的调试器，仅限本机临时使用** |
| `FLASK_HOST` | `127.0.0.1` | 监听地址。**默认只允许本机访问**；改为 `0.0.0.0` 需自行确认网络环境可信 |
| `FLASK_PORT` | `5000` | 监听端口 |
| `FRONTEND_MODE` | `spa` | `spa` 使用 React 前端；`classic` 回退 Jinja2 模板 |
| `LOG_LEVEL` | `INFO` | 日志级别。`DEBUG` 会连带打印请求体等敏感内容，仅限本机排障临时开启 |
| `LOG_FILE` | 空（只输出到控制台） | 设置后额外写入日志文件并自动轮转（5MB × 3）。相对路径按 `web_auth/logs/` 解析 |
| `MAX_CONTENT_LENGTH` | `16777216`（16MB） | 请求体大小上限 |
| `MONGO_SERVER_SELECTION_TIMEOUT_MS` | `5000` | 数据库选择超时。`MONGO_URI` 中已指定时以 URI 为准 |

管理后台入口：`/manage/login`

> ⚠️ **安全提示**：默认管理员口令仅用于本地开发。请通过环境变量覆盖后再部署。
>
> **调试模式默认关闭**：`app.run()` 只是本地开发入口。调试模式一旦开启，Werkzeug 会暴露
> 可执行任意代码的交互式调试器，并显示完整堆栈与配置（含数据库连接串）。
> 生产环境请改用 WSGI 服务器，并保持 `FLASK_DEBUG=0`：
>
> ```bash
> gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 web_auth.app:app
> ```
>
> 说明：本项目使用进程内的设备连接状态与模型缓存，因此**建议单进程多线程**（`-w 1 --threads N`）。
> 另外 `FLASK_SECRET_KEY` 未设置时会随机生成，多 worker 之间密钥不一致会导致登录状态随机失效，
> 多进程部署务必显式配置该变量。
>
> 数据库索引（含 `username` 唯一索引）在**进程启动时**自动创建，与使用开发服务器还是 WSGI 服务器无关。
> 若启动日志出现「系统初始化未完成」，说明当时数据库不可达、索引未建立 —— 请确认 MongoDB 可访问后重启。

## 说明

- **模型权重不入库**：`*.pth` 已加入 `.gitignore`。个人模型在用户完成注册采集后由训练流程生成，可用仓库内训练脚本复现。
- **前端适配层**：`spa_adapter.py` 采用「包装既有视图函数」的方式，使 GET 请求返回 SPA、POST 请求保持原有表单语义，后端业务逻辑无需改动。设置 `FRONTEND_MODE=classic` 可随时切回 Jinja2 页面。

## 贡献者

| 贡献者 | 主要贡献 |
|---|---|
| [@Zzthird](https://github.com/Zzthird) | **项目原始原型**：设备接入（BLE 蓝牙 / 串口）、信号采集与预处理流水线、BiLSTM 模型训练与认证比对逻辑、MongoDB 存储层 |
| [@Durian2005](https://github.com/Durian2005) | **前端重构与开源整理**：React SPA 全站重建、Flask 适配层、项目脱敏与文档、发布维护 |

> 原始原型完成于 2025 年 8 月，前端重构与开源整理完成于 2026 年 9 月。
> 仓库保留了完整的开发提交历史，贡献者名单由提交作者自动统计。

## 许可

仅用于学习与研究用途。
