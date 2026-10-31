# 当前项目结构图

项目根目录：`E:\qwen-local\qwen-local`。按当前实际文件整理，模型缓存和Python缓存不逐项展开。

```text
qwen-local/
├── backend/                                  后端程序
│   ├── __init__.py                           Python包标记
│   ├── main.py                               FastAPI入口、会话接口、SSE流式输出、用户归属校验
│   ├── auth.py                               注册/登录/退出、Argon2密码哈希、Redis登录会话、认证限流
│   ├── courts.py                             共享法庭、10人上限、权限、阶段、SSE同步与共享AI
│   ├── config.py                             PostgreSQL/Redis连接、Cookie安全设置、允许的网页来源
│   ├── database.py                           PostgreSQL连接池及用户、会话、消息表定义
│   ├── inference_client.py                   调用本机vLLM接口、输入token预算、流式解析与取消
│   ├── generation_queue.py                   5个生成名额＋5个等待位置，每账号1个请求，FIFO排队
│   ├── model_service.py                      旧版Transformers本地模型推理模块，当前启动入口不使用
│   └── __pycache__/                          Python自动生成的编译缓存
│
├── frontend/                                 网页前端
│   ├── index.html                            登录/注册、聊天界面、历史记录、流式显示和排队提示
│   ├── courts.js                             个人/法庭切换、创建加入、成员权限与房间交互
│   ├── courts.css                            法庭工具栏、弹窗与响应式样式
│   └── vendor/                               本地前端依赖，无须从公网CDN加载
│       ├── marked.umd.js                     Markdown渲染库
│       ├── purify.min.js                     DOMPurify，清理渲染内容中的不安全HTML
│       ├── README.md                         依赖说明
│       ├── marked-LICENSE.md                 marked许可证
│       └── DOMPurify-LICENSE-MPL              DOMPurify许可证
│
├── migrations/                               Alembic数据库结构迁移
│   ├── env.py                                加载数据库连接与SQLAlchemy表定义
│   ├── script.py.mako                        新迁移文件模板
│   └── versions/
│       ├── 0001_users_chat.py                 创建用户、会话、消息表及索引
│       ├── 0002_court_rooms.py                创建法庭、成员、共同消息表
│       └── 0003_court_roles.py                创建者改法官，旧讨论者改待分配
│
├── deploy/
│   └── local/                                本机容器部署和验证材料
│       ├── compose.yaml                      PostgreSQL 17＋Redis 7.4，持久化数据卷与健康检查
│       ├── compose.inference.yaml            GPU运行vLLM，挂载Qwen3-8B，最多5个并发序列
│       ├── .env                              PostgreSQL密码配置，含敏感信息，不应公开
│       ├── .gitignore                        忽略.env
│       ├── README.md                         容器部署与使用说明
│       ├── CAPACITY.md                       4090并发测试结果、当前容量与测试限制
│       ├── test_parallel.py                  两个请求同时生成验证
│       ├── test_accounts.py                  登录、用户隔离、会话持久化与双账号流式验证
│       ├── benchmark_capacity.py             4/5个请求的并发性能测试
│       ├── capacity-results.json             常规并发测试记录
│       ├── capacity-stress.json              长输入、长输出测试记录
│       ├── queue-results.json                生成名额和有限排队测试记录
│       └── login-preview.png                 登录页面预览截图
│
├── models/                                   本地模型文件
│   ├── Qwen3-8B/                             当前vLLM使用的模型，FP16推理
│   │   ├── config.json                       模型结构配置
│   │   ├── configuration.json                随模型保留的配置文件
│   │   ├── generation_config.json            默认生成参数
│   │   ├── tokenizer.json                    分词器数据
│   │   ├── tokenizer_config.json             分词器及聊天模板配置
│   │   ├── vocab.json                        词表
│   │   ├── merges.txt                        Token合并规则
│   │   ├── model.safetensors.index.json       模型权重分片索引
│   │   ├── model-00001-of-00005.safetensors   权重分片1
│   │   ├── model-00002-of-00005.safetensors   权重分片2
│   │   ├── model-00003-of-00005.safetensors   权重分片3
│   │   ├── model-00004-of-00005.safetensors   权重分片4
│   │   ├── model-00005-of-00005.safetensors   权重分片5
│   │   └── .cache/                           模型下载缓存
│   └── Qwen3-4B/                             旧模型保留目录，当前服务不使用
│
├── data/
│   └── chat.db                               旧SQLite测试数据库，当前服务不读写、不迁移
│
├── logs/                                     旧版启动脚本生成的日志与进程记录
│   ├── qwen8b.stdout.log                      标准输出日志
│   ├── qwen8b.stderr.log                      错误日志
│   └── qwen8b.pid                             旧进程编号记录，不代表当前服务仍运行
│
├── serve_vllm.py                             本机HTTP网页启动入口：127.0.0.1:8000，单worker
├── serve_public.py                           公网HTTPS隧道启动入口：允许zss.nat200.top，Secure Cookie
├── requirements-web.txt                      网页后端依赖及版本
├── alembic.ini                               数据库迁移工具配置
├── START_STOP.md                             本机完整启动、检查和关闭流程
├── PUBLIC_ACCESS.md                          NATAPP公网入口配置、启动和验收流程
├── ACCOUNTS.md                               多用户账号、数据隔离与使用说明
├── COURTS_UPDATE.md                          多人模拟法庭功能、文件变更和验收说明
├── PROJECT_STRUCTURE.md                      本结构说明
├── serve_qwen8b.py                           旧版启动入口，当前方案不使用
├── start_qwen8b.ps1                           旧版PowerShell启动脚本，当前方案不使用
├── DEPLOY_QWEN8B.md                          旧版模型部署说明
└── __pycache__/                              Python编译缓存
```

## 当前运行结构

```text
实验组成员的浏览器
        │ HTTPS：https://zss.nat200.top
        ▼
NATAPP公网中转服务器
        │ 穿透隧道（需客户端Online才可访问）
        ▼
本机NATAPP客户端                            程序在项目目录之外
E:\软件\natapp_windows_amd64_3_0_5\
├── natapp.exe                              隧道客户端
└── config.ini                              隧道密钥配置，不应公开
        │ 转发到127.0.0.1:8000
        ▼
FastAPI网页后端（serve_public.py，单worker）
├── frontend/index.html                     登录和聊天网页
├── auth.py ────────── Redis :6379           登录凭证与认证限流
├── database.py ────── PostgreSQL :5432      用户、会话和消息持久化
└── generation_queue.py                     5生成＋5排队，等待最多120秒
        │ inference_client.py，调用本地HTTP接口
        ▼
vLLM Docker容器 :8001
        │ 加载本地Qwen3-8B权重
        ▼
RTX 4090 24GB                              执行模型计算
```

本机访问时由浏览器直接连接8000，使用serve_vllm.py；公网模式使用serve_public.py，两者不能同时占用8000。PostgreSQL、Redis和vLLM端口均只绑定本机地址，NATAPP仅映射网页8000。

当前聊天数据保存在Docker命名数据卷中，而非data/chat.db：

| 数据卷 | 用途 |
|---|---|
| qwen-local-infra_postgres_data | PostgreSQL用户、会话、消息及迁移版本 |
| qwen-local-infra_redis_data | Redis持久化数据，包括登录会话与限流计数 |
| qwen-local-inference_inference_cache | vLLM运行缓存 |

这些数据卷由Docker Desktop管理，不是项目目录中的普通文件夹。容器正常stop不会删除数据；down -v会删除相关数据卷。

并发队列位于FastAPI进程内，未使用Redis消息队列；Redis目前负责认证与限流。此实现要求单worker，尚未支持多个业务实例协调生成名额。公网配置已准备，隧道连通与HTTPS流式聊天仍需要实际验收，不能仅根据目录或配置认定上线成功。
