# 当前推理服务：Strata IQ2_XS

输入框上方的模型菜单可逐请求选择关闭/低/中/高思考与 四档回答多样性（0.2/0.4/0.7/1.0），保存在当前浏览器。提交后参数固定，排队或生成中修改只影响下一次请求。法庭由主持人/管理员发起 AI 时携带所选参数。低/中/高思考预算分别为 256/512/1024 token，和最终回答共用 2048 输出上限；最终回答入库，内部思考以小字临时流式显示，答案开始生成即隐藏，不写入历史。无需重启 Strata。

历史策略：个人聊天取消最近 20 条限制，按实际 token 预算保留最近的完整问答轮次；法庭取消最近 60 条限制，按预算保留完整发言及身份。系统提示和当前问题始终保留，超过预算仅裁剪本次模型输入，不删除数据库记录。尚未加入旧历史摘要。

网站默认连接 http://127.0.0.1:8080，模型名 strata。输入预算 32768 token，输出上限 2048 token；关闭思考。默认 3 个生成名额、5 个等待位置，排队超时仍为 120 秒。个人聊天与共享法庭共用推理客户端和队列。

## 启动网站

先保持 Strata 运行，停止旧 vLLM 推理容器。数据库和 Redis 沿用原有数据卷，无需迁移。

```powershell
cd E:\qwen-local\qwen-local\deploy\local
docker compose -f compose.inference.yaml stop inference
docker compose up -d --wait
cd E:\qwen-local\qwen-local
& 'D:\Anaconda\envs\qwen-local-new\python.exe' serve_vllm.py
```

脚本名称为兼容旧操作保留，默认推理服务已改为 Strata。原 serve_public.py 也使用同一默认配置。启动前关闭已有网站后端，避免 8000 端口冲突。

访问 http://127.0.0.1:8000；检查 http://127.0.0.1:8000/api/health，inference_provider 应为 strata，model_loaded 应为 true。

## 自定义配置

在启动后端的 PowerShell 中设置环境变量：

```powershell
$env:INFERENCE_PROVIDER = 'strata'
$env:INFERENCE_BASE_URL = 'http://127.0.0.1:8080/v1'
$env:INFERENCE_MODEL = 'strata'
$env:INFERENCE_API_KEY = 'none'
```

支持 INFERENCE_MAX_INPUT_TOKENS、INFERENCE_MAX_NEW_TOKENS、INFERENCE_QUANTIZATION；输入加输出预算必须不超过 Strata 的实际 max_context。当前 Strata 配置 parallel=3，网站默认 GENERATION_SLOTS=3；个人聊天和法庭 AI 共用这三个名额。之后增减并发需要两处同步调整并重启。

## 切回 Qwen3-8B

先停止网站后端、关闭 Strata，等待显存释放。在新的 PowerShell 窗口执行，避免遗留自定义 INFERENCE_* 配置：

```powershell
cd E:\qwen-local\qwen-local\deploy\local
docker compose -f compose.inference.yaml up -d inference
cd E:\qwen-local\qwen-local
$env:INFERENCE_PROVIDER = 'vllm'
& 'D:\Anaconda\envs\qwen-local-new\python.exe' serve_vllm.py
```

vLLM 模式默认恢复端口 8001、qwen3-8b、3072 输入预算、1024 输出预算和 5 个生成名额。原 VLLM_BASE_URL、VLLM_MODEL 仍受支持。

停止容器不会删除历史数据；不要使用 docker compose down -v。

