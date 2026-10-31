# 本地基础设施与独立推理验证

在本目录的 Windows PowerShell 中执行。需要运行中的 Docker Desktop（WSL2/Linux 容器）。

## PostgreSQL / Redis

```powershell
docker compose up -d --wait
docker compose exec postgres psql -U qwen -d qwen -c "SELECT 1;"
docker compose exec redis redis-cli ping
```

PostgreSQL：127.0.0.1:5432，数据库/用户均为 qwen，密码在本目录 .env。
Redis：127.0.0.1:6379，本地开发无密码。不要将此配置直接用于公网。
数据保存于命名卷。停止服务用 `docker compose stop`；不要使用 `down -v`，它会删除数据卷。

## 独立推理服务

```powershell
docker compose -f compose.inference.yaml up -d
docker compose -f compose.inference.yaml logs -f inference
```

API：http://127.0.0.1:8001，健康检查 /health，模型列表 /v1/models。
模型名称 qwen3-8b，接口 /v1/chat/completions。
使用原有 Qwen3-8B 权重只读挂载，不重新下载模型。
vLLM 0.31.0 官方镜像已固定 AMD64 摘要。
配置为 FP16、eager、总上下文 4096、最多 2 个活动序列、显存预算 80%。
这是独立验证环境，与旧 Transformers INT8 推理不同。
请求中使用 `chat_template_kwargs: {"enable_thinking": false}` 关闭 thinking。
不要同时启动原来的 GPU 模型服务。

停止推理：

```powershell
docker compose -f compose.inference.yaml stop
```

## 验证结果（2026-10-05）

基础设施 SQL SELECT 1、Redis PONG 已通过。
推理服务 /health 返回 200，单请求生成通过。
两个流式请求同时提交，连续四轮每路生成 256 token（finish_reason=length），均观察到流式输出重叠。
每路耗时约 5.37–5.63 秒，输出重叠约 5.29–5.31 秒。
服务日志记录 Running: 2 reqs、Waiting: 0 reqs。
首轮首文本延迟约 0.30–0.33 秒；后续重复提示受到前缀缓存影响。
该验证限于短输入、256 token 输出，不能代表满上下文容量、长时间稳定性或完整任务质量。
业务后端与网页已接入独立 vLLM。现已增加注册登录，聊天历史使用 PostgreSQL；旧SQLite测试数据不迁移。详见 ../../ACCOUNTS.md。

## 8000 网页启动

先确保推理容器运行，再在项目根目录执行：

```powershell
& 'D:\Anaconda\envs\qwen-local-new\python.exe' serve_vllm.py
```

访问 http://127.0.0.1:8000 。新后端只依赖 HTTPX 访问模型，不导入旧 GPU 模型服务。
依赖：FastAPI、Uvicorn、SQLAlchemy、HTTPX；当前环境均已验证存在。
暂时只运行一个业务 worker，因为会话占用和两个并发名额在进程内维护。
满额返回 429；同会话重复生成返回 409；过长当前问题返回 400，不截断当前问题。
历史按完整消息裁剪，保留系统提示与当前问题，输入 3072 / 输出 1024。
断线关闭上游流并释放名额；失败不保存不完整助手回答，已提交用户消息仍保留。
取消后的正式请求状态与重试幂等将在后续账号/数据库阶段实现。
网页吞吐指标按输出 token / 上游请求总耗时计算，包含首文本等待；不冒充 GPU 原生指标。
2026-10-05 实际验证两个不同会话各生成 1024 token：约 21.8 秒，输出重叠约 21.3 秒，分别入库成功。
验证同会话 409、断线后释放名额、普通非流式生成、过长问题 400，以及 HTML 网页可访问。
API 流程已验证；没有进行两个浏览器窗口的人工视觉操作验证。

复现并发测试：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& 'D:\Anaconda\envs\qwen-local-new\python.exe' test_parallel.py
```

测试失败返回非零退出码。脚本检查两路首文本至结束的区间重叠，不将请求提交重叠误认为生成并发。

当前容量已升级为五个生成名额＋五个排队位置，详见 CAPACITY.md。上文双请求数据是之前的验证记录。
