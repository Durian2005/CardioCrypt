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
├── web_auth/                  # Web 应用
│   ├── __init__.py            # 应用工厂 create_app()（注册蓝图 / 适配层 / 全局钩子）
│   ├── app.py                 # 开发服务器入口（薄壳，只读 HOST / PORT / DEBUG）
│   ├── config.py              # 配置分层：环境变量读取 + 日志初始化
│   ├── extensions.py          # 扩展实例（PyMongo / 限流器 / CSRF），用于打断循环导入
│   ├── state.py               # 进程内可变状态 + 闲置回收
│   ├── core.py                # 算法层导入与降级、模型缓存、系统初始化、权限装饰器
│   ├── security.py            # 限流器与 CSRF 防护原语
│   ├── demo.py                # 演示模式（DEMO_MODE）的降级出口与合成信号生成
│   ├── blueprints/            # 路由分层
│   │   ├── auth.py            #   首页 / 注册 / 登录登出
│   │   ├── device.py          #   设备扫描连接 / 数据采集 / 认证执行
│   │   ├── dashboard.py       #   用户仪表盘与状态轮询
│   │   └── admin.py           #   管理后台
│   ├── services/              # 无状态业务函数
│   │   ├── signals.py         #   信号指标提取与特征组装
│   │   ├── collection.py      #   BLE / 串口数据采集（验证与注册共用）
│   │   ├── health.py          #   心率 / 情绪 / 告警等级计算
│   │   └── stats.py           #   真实统计聚合（认证次数 / 运行时长等）
│   ├── spa_adapter.py         # React SPA 适配层（GET→SPA，POST→原逻辑）
│   ├── frontend/              # React 前端源码
│   │   └── src/
│   │       ├── pages/         # 页面
│   │       ├── components/    # 组件
│   │       └── lib/           # API 客户端与工具
│   ├── static/                # 静态资源（含前端构建产物 dist/）
│   └── templates/             # 旧版 Jinja2 模板（classic 模式保留）
├── ecgppg_system/             # 信号处理 / 设备 / 模型 / 可视化 核心库
├── model_example/             # 模型封装模块（训练、评估、推理）
├── tests/                     # pytest 回归集
├── pytest.ini
└── requirements.txt
```

后端已从单文件拆分为「工厂 + 分层模块 + 4 个蓝图」：原 `app.py` 由 3000 余行收缩到
不足 60 行的入口壳，路由按职责分散到 `blueprints/`，配置、扩展实例、进程内状态与
算法层适配各自独立成模块。改配置或加路由不必再在一个巨文件里翻找。

## 快速开始

> 更详细的启动步骤、页面导览、使用场景与常见问题排查，见 **[使用指南.md](使用指南.md)**。也可直接双击根目录的 `start.bat` 一键启动。

### 1. 环境准备

需要 **Python 3.9.x**。依赖清单已锁定到该版本可安装的精确版本，并按用途分组；
标 `sys_platform == "win32"` 的 `winrt-*` 系列是 Windows 上 BLE 的后端，其他平台会自动跳过。

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

需要本地运行 **MongoDB**（默认 `mongodb://localhost:27017`）。

如果要运行测试，改装 `requirements-dev.txt` —— 它通过 `-r` 引入运行时依赖，并额外提供 pytest：

```bash
pip install -r requirements-dev.txt
```

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

### 4. 运行测试

```bash
venv\Scripts\python.exe -m pytest
```

测试通过环境变量把 `MONGO_URI` 指向**独立临时库** `ecg_auth_db_pytest`
（在 `tests/conftest.py` 顶部注入，必须早于 `import web_auth`），不会读写开发库
`ecg_auth_db`。运行前请确保本地 MongoDB 可用。

| 文件 | 覆盖范围 |
|---|---|
| `tests/test_security.py` | 限流器边界与窗口滑动、CSRF 令牌的生成 / 轮换 / 会话绑定 |
| `tests/test_auth_flow.py` | 登录 / 注册 / 登出流程、反用户枚举、会话固定防护、判定结论完整性 |
| `tests/test_authentication.py` | 信号相似度的性质型断言，并固定两处已知缺陷 |
| `tests/test_model_authentication.py` | 认证实现的判定契约：EER 不随阈值变化、推理失败与判定不通过可区分、融合结果内部自洽 |
| `tests/test_admin_api.py` | 管理接口的权限边界、口令长度与限流、响应字段脱敏 |
| `tests/test_spa.py` | SPA 适配层的会话投影、令牌下发、未知路径仍返回真 404 |
| `tests/test_demo_mode.py` | 演示模式：默认关闭时采集不到数据必须判失败，开启后结果带 `demo` 标记且判定规则不变 |

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017/ecg_auth_db` | MongoDB 连接串 |
| `ADMIN_USERNAME` | `admin` | 管理后台账号 |
| `ADMIN_PASSWORD` | `admin123` | 管理后台口令 —— **部署前必须修改** |
| `FLASK_SECRET_KEY` | 自动生成并持久化到 `web_auth/.flask_secret_key` | 会话签名密钥。未设置时自动生成一份本地密钥文件，使同一部署内的多个进程共享同一密钥 |
| `FLASK_DEBUG` | `0` | 设为 `1` 开启调试模式。**会暴露可执行任意代码的调试器，仅限本机临时使用** |
| `FLASK_HOST` | `127.0.0.1` | 监听地址。**默认只允许本机访问**；改为 `0.0.0.0` 需自行确认网络环境可信 |
| `FLASK_PORT` | `5000` | 监听端口 |
| `FRONTEND_MODE` | `spa` | `spa` 使用 React 前端；`classic` 回退 Jinja2 模板 |
| `LOG_LEVEL` | `INFO` | 日志级别。`DEBUG` 会连带打印请求体等敏感内容，仅限本机排障临时开启 |
| `LOG_FILE` | 空（只输出到控制台） | 设置后额外写入日志文件并自动轮转（5MB × 3）。相对路径按 `web_auth/logs/` 解析 |
| `MAX_CONTENT_LENGTH` | `16777216`（16MB） | 请求体大小上限 |
| `MONGO_SERVER_SELECTION_TIMEOUT_MS` | `5000` | 数据库选择超时。`MONGO_URI` 中已指定时以 URI 为准 |
| `CSRF_ENABLED` | `1` | 写操作的 CSRF 校验开关。**默认开启，不建议关闭** |
| `DEMO_MODE` | `0` | 演示模式。开启后，采集不到真实设备信号时改用合成数据把流程走完，并在日志、接口与界面上逐处标注。**详见下节** |
| `STATE_TTL_SECONDS` | `3600` | 内存中注册 / 验证状态的闲置回收时长（秒） |
| `STATE_CLEANUP_INTERVAL` | `300` | 闲置状态的扫描间隔（秒） |
| `MAX_CACHED_MODELS` | `50` | 内存中缓存的用户模型上限 |

管理后台入口：`/manage/login`

> ⚠️ **安全提示**：默认管理员口令仅用于本地开发。请通过环境变量覆盖后再部署。
>
> **调试模式默认关闭**：`app.run()` 只是本地开发入口。调试模式一旦开启，Werkzeug 会暴露
> 可执行任意代码的交互式调试器，并显示完整堆栈与配置（含数据库连接串）。
> 生产环境请改用 WSGI 服务器，并保持 `FLASK_DEBUG=0`：
>
> ```bash
> gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 'web_auth:create_app()'
> ```
>
> 其余 WSGI 服务器同理，加载目标为应用工厂 `web_auth:create_app()`（`web_auth.app:app`
> 作为开发入口也仍然可用）。
>
> 说明：本项目使用进程内的设备连接状态与模型缓存，因此**建议单进程多线程**（`-w 1 --threads N`）。
> 会话密钥未显式配置时会自动生成并持久化到 `web_auth/.flask_secret_key`，同一部署内的多个进程
> 因此共享同一密钥、不会出现登录状态随机失效；生产环境仍建议显式配置 `FLASK_SECRET_KEY`。
>
> **CSRF 防护默认开启**：所有写操作（POST/PUT/PATCH/DELETE）都必须携带与会话绑定的令牌。
> 页面由后端渲染时令牌会自动注入（隐藏字段 + `meta` 标签 + ajax 全局请求头）。
> 若自行编写脚本调用写接口，需先 `GET /api/csrf-token` 取令牌，再以 `X-CSRFToken`
> 请求头（或表单字段 `csrf_token`）提交；GET 等安全方法不受影响。
>
> 数据库索引（含 `username` 唯一索引）在**进程启动时**自动创建，与使用开发服务器还是 WSGI 服务器无关。
> 若启动日志出现「系统初始化未完成」，说明当时数据库不可达、索引未建立 —— 请确认 MongoDB 可访问后重启。
>
> 内存中的注册 / 验证状态会按 `STATE_TTL_SECONDS` 自动回收闲置条目；
> 前端轮询状态接口时会刷新活跃时间，因此进行中的流程不会被误清。

### 演示模式（`DEMO_MODE`）

采集依赖真实硬件：注册与验证都要求先扫描到设备、再采到信号。没有硬件时这两条
流程走不完 —— 而这恰恰是功能演示最常见的场景。

`DEMO_MODE=1` 提供一条**显式**的演示通路：采集不到真实数据时，改用合成信号把
流程走完。默认关闭，且开启后不能放宽任何判定。

```bash
DEMO_MODE=1 venv\Scripts\python.exe web_auth\app.py
```

它改的是**数据从哪来**，不是**判定怎么下**：

- 合成信号**照常**送入模型比对，**照样可能不通过** —— 它不会把「不通过」改写成「通过」；
- 用户模型**不会被伪造**。算法层不可用时注册直接中止，既不写占位模型文件，也不写入用户；
- 每一次降级都留痕：日志以 `[DEMO]` 前缀记 WARNING，验证与注册的接口返回
  `demo: true` 及降级原因，SPA 与 classic 界面都会显示醒目的提示条。

开启后，设备扫描步骤会多出一个「演示模式：跳过设备，使用合成数据」入口。
**用它跑出来的任何结果都不代表真实生物特征比对**，请勿用于验收或模型评估。

## 安全设计

下表列出各项防护的**设计意图**与**已知边界**。写清楚边界和写清楚措施同样重要 ——
一个「看起来有防护、实际在多进程下打折」的限流器，比没有限流器更容易让人误判。

| 措施 | 设计意图 | 已知边界 / 代价 |
|---|---|---|
| 认证前清空会话 | 防会话固定攻击：攻击者预先植入的会话 ID 在认证成功后失效 | 清空前会保留 CSRF 令牌（`clear_session_keep_csrf`），否则紧随其后的表单提交必然失败 |
| CSRF 双层令牌 | 令牌与会话绑定，覆盖 JSON 请求头（SPA）与隐藏表单字段（原生页面）两条通路 | 令牌与会话共存亡；脚本调用写接口前必须先 `GET /api/csrf-token` |
| 登录频率限制 | 同一 IP 每分钟 10 次；管理登录使用独立配额，避免两者互相挤占 | **进程内**滑动窗口。多 worker 部署时各自计数，等效配额为 `N × 10`；只有单进程多线程下语义才完全成立 |
| 统一失败措辞 | 不区分「用户不存在」与「口令错误」，消除用户名枚举 | 用户拿不到具体原因，排障需查服务端日志 |
| 判定结论唯一来源 | 判定只由算法输出决定，不提供任何可以覆盖结果的请求参数 | 副作用是无真实硬件时注册 / 认证流程走不通，必须接入设备才能完整演示 |
| 上传体积上限 | `MAX_CONTENT_LENGTH` 默认 16MB，避免超长请求体拖垮进程 | 超限直接返回 413，长信号需自行分段 |
| 错误信息不泄漏路径 | 管理接口只返回模型文件名，不下发本机绝对路径 | 该字段仍被两个管理页渲染，改名会连带影响前端与模板 |
| 密钥可持久化 | 未显式配置时自动生成并写入 `web_auth/.flask_secret_key`，使同机多进程共享密钥 | 生产环境仍应显式配置 `FLASK_SECRET_KEY`；密钥文件在文件系统不可写时退回进程内随机值并打印告警 |

> **部署形态约束**：设备连接状态、验证结果与模型缓存都是**进程内状态**，
> 因此必须**单进程多线程**运行（`-w 1 --threads N`）。多进程会让请求落到互不相见的副本上 ——
> 限流计数、设备状态、进行中的采集流程各算各的。
>
> **后续规划**：把设备会话、验证结果与模型缓存挪到进程外（Redis 或独立设备服务），
> 是支持多用户并发的真正前提；本项目按课程实践范围暂不实施。

## 说明

- **模型权重不入库**：`*.pth` 已加入 `.gitignore`。个人模型在用户完成注册采集后由训练流程生成，可用仓库内训练脚本复现。
- **前端适配层**：`spa_adapter.py` 采用「包装既有视图函数」的方式，使 GET 请求返回 SPA、POST 请求保持原有表单语义，后端业务逻辑无需改动。设置 `FRONTEND_MODE=classic` 可随时切回 Jinja2 页面。
- **一份已废弃的认证实现**：`ecgppg_system/utils/authentication.py` 是早期原型的认证实现，已被 `model_example/authentication.py` 取代，当前没有任何调用方。已在模块头标注废弃并保留实现 —— 保留是为了不抹去原始贡献者的代码与提交历史；该模块存在若干已知限制，详见其 docstring。
- **算法层可降级**：`ecgppg_system` / `model_example` 导入失败时，Web 应用仍能启动并给出明确报错，而不是让 import 直接炸掉整个进程，便于单独调试 Web 层。

## 贡献者

| 贡献者 | 主要贡献 |
|---|---|
| [@Zzthird](https://github.com/Zzthird) | **项目原始原型**：设备接入（BLE 蓝牙 / 串口）、信号采集与预处理流水线、BiLSTM + Attention 模型训练与认证比对逻辑、MongoDB 存储层 |
| [@Durian2005](https://github.com/Durian2005) | **前端重构、安全加固与工程整理**：React SPA 全站重建与 Flask 适配层；CSRF 防护与登录限流、会话与密钥管理、数据库索引随进程启动初始化；应用工厂与蓝图分层重构、pytest 回归集（107 例）；依赖清单治理、演示模式开关、项目脱敏、文档与发布维护 |

> 原始原型完成于 2025 年 8 月；前端重构、安全加固与工程整理完成于 2026 年 9 月。
> 仓库保留了完整的开发提交历史，贡献者名单由提交作者自动统计。

## 许可

仅用于学习与研究用途。
