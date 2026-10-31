# 本地服务启动与关闭流程

> 2026-10-12 更新：网站默认已切换至 Strata IQ2_XS。当前启动及切回 Qwen3-8B 请按 [STRATA_SWITCH.md](STRATA_SWITCH.md) 操作。以下 vLLM 启动步骤保留供旧模式参考；不要在 Strata 占用显存时启动 vLLM。

适用于当前 Windows + Docker Desktop（WSL2）+ RTX 4090 环境。项目目录为 `E:\qwen-local\qwen-local`。PowerShell 显示 `(base)` 不影响下面的操作：后端直接使用指定环境的 Python。

## 一、重启电脑后的启动流程

### 1. 打开 Docker Desktop

从开始菜单启动 Docker Desktop，等它显示引擎已运行。Ubuntu 无须另外打开终端。保持 Docker Desktop 运行。

打开普通 PowerShell，检查：

```powershell
docker version
```

应同时有 Client 和 Server 信息。如果提示找不到 docker，在当前窗口执行：

```powershell
$env:Path = 'C:\Users\ss\AppData\Local\Programs\DockerDesktop\resources\bin;' + $env:Path
docker version
```

### 2. 启动 PostgreSQL 和 Redis

```powershell
cd E:\qwen-local\qwen-local\deploy\local
docker compose up -d --wait
docker compose ps
```

两个服务应为 running / healthy。即便已经自动启动，再执行这一步也可以。

### 3. 启动本地大模型推理服务

不要同时运行旧模型脚本或其他占用大量显存的程序。

```powershell
docker compose -f compose.inference.yaml up -d
docker compose -f compose.inference.yaml logs -f --tail 50 inference
```

模型加载需要等待，看到服务启动后，按 `Ctrl+C` 退出日志查看；这不会停止容器。

验证模型已就绪：

```powershell
(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8001/health).StatusCode
```

返回 `200` 才继续。尚未就绪时等待后再检查；`/health` 正常响应没有正文，浏览器空白是正常的。

也可查看模型名称：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/v1/models
```

### 4. 启动聊天网页后端

在同一个 PowerShell 中执行：

```powershell
cd E:\qwen-local\qwen-local
& 'D:\Anaconda\envs\qwen-local-new\python.exe' -m alembic upgrade head
& 'D:\Anaconda\envs\qwen-local-new\python.exe' serve_vllm.py
```

数据库升级命令可重复执行；已经是最新版本时不会重复建表。升级失败时先处理报错，再启动后端。

看到 `Uvicorn running on http://127.0.0.1:8000` 后，保持这个窗口打开。

### 5. 打开网页

访问 **http://127.0.0.1:8000/**，使用之前注册的账号登录即可。账号、聊天记录保存在 PostgreSQL，正常关闭和重启后保留。登录凭证有效期为24小时，过期后重新登录。

当前配置：5个同时生成名额、5个等待位置、每账号最多1个正在生成或排队的请求，排队超时120秒。不同账号测试用不同浏览器或隐私窗口。

## 二、正常关闭流程

1. 等正在生成的回答结束，避免回答中途被打断。
2. 在运行 `serve_vllm.py` 的 PowerShell 窗口按 `Ctrl+C`，等后端退出。
3. 在 PowerShell 执行下面命令，依次停止推理、数据库和 Redis：

```powershell
cd E:\qwen-local\qwen-local\deploy\local
docker compose -f compose.inference.yaml stop
docker compose stop
```

4. 如需完全退出，在 Docker Desktop 托盘菜单选择 Quit Docker Desktop。之后可以正常关闭电脑。

这里使用 `stop`，保留容器和数据卷。**不要执行 `docker compose down -v` 或删除数据库数据卷**，否则会删除其中的账号和聊天记录。不要删除 `deploy/local/.env`，其中保存数据库连接密码。

只想临时停网页，可以仅停止后端；只想释放显存，可以停止推理容器。完整使用时三个基础服务和网页后端都要运行。

## 三、常用检查与故障排查

另开一个 PowerShell：

```powershell
cd E:\qwen-local\qwen-local\deploy\local
docker compose ps
docker compose -f compose.inference.yaml ps
docker compose exec postgres psql -U qwen -d qwen -c "SELECT 1;"
docker compose exec redis redis-cli ping
(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8001/health).StatusCode
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/health
```

预期 PostgreSQL 返回1、Redis 返回PONG、推理健康检查返回200，网页后端健康接口返回状态信息。

查看日志：

```powershell
docker compose logs --tail 100 postgres redis
docker compose -f compose.inference.yaml logs --tail 100 inference
```

- Docker 没有 Server 信息：确认 Docker Desktop 引擎已启动。
- 8001连接失败：检查推理容器日志，模型可能仍在加载；若出现显存不足，先关闭其他模型程序，再重启推理容器。
- 网页8000打不开：确认运行后端的 PowerShell 仍在运行，没有启动报错。
- 8000端口被占用：检查是否已有后端运行，不要重复启动多个实例。
- 推理服务根路径8001返回 Not Found：正常，请用 `/health` 或 `/v1/models` 检查。聊天网页地址是8000。
- `.env`、模型目录、Python环境已准备好，日常重启不需要重新安装依赖或下载模型。

## 四、启动顺序速记

**Docker Desktop → PostgreSQL / Redis → vLLM（健康200）→ 数据库升级 → FastAPI → 打开8000网页。**

关闭顺序：**等待回答结束 → FastAPI → vLLM → PostgreSQL / Redis → Docker Desktop。**
