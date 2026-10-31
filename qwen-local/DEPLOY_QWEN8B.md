# Qwen3-8B 本地部署（LLM.int8）

## 1. 使用已有环境

在 PowerShell 或 Anaconda Prompt 中执行：

```powershell
conda activate qwen-local-new
cd E:\qwen-local\qwen-local
python -c "import sys, torch; print(sys.executable); print(torch.cuda.is_available())"
```

Python 应指向 `D:\Anaconda\envs\qwen-local-new\python.exe`，CUDA 应输出 True。
当前基础环境的 Transformers 太旧，不要使用基础环境运行服务。
如果当前终端无法识别 conda，可在 Anaconda Prompt 激活环境后运行。

## 2. 本地权重

模型已经下载至 models/Qwen3-8B，日常启动不需要再次下载。
本次使用 ModelScope 官方 Qwen/Qwen3-8B 仓库，5 个原始权重分片完整保留。
加载时由 bitsandbytes 执行 LLM.int8()。一次性下载、验证脚本及旧备份已清理。

## 3. 启动网页

在 PowerShell 执行：

```powershell
.\start_qwen8b.ps1
```

启动脚本默认使用 `D:\Anaconda\envs\qwen-local-new\python.exe`。
需要后台运行时：

```powershell
.\start_qwen8b.ps1 -Background
```

后台运行日志位于 logs/qwen8b.stdout.log 和 logs/qwen8b.stderr.log，进程编号保存至 logs/qwen8b.pid。
不要在已有服务运行时再启动第二个进程。

若本机脚本策略阻止执行，可直接在已激活环境的 PowerShell 执行：

```powershell
$env:QWEN_MODEL_PATH = 'E:\qwen-local\qwen-local\models\Qwen3-8B'
$env:QWEN_QUANTIZATION = 'int8'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器访问 http://127.0.0.1:8000 ，健康检查为 http://127.0.0.1:8000/api/health。
健康检查应显示 Qwen3-8B、int8、model_loaded=true。
只使用一个 worker，避免重复加载模型。

## 4. 关闭服务

前台运行时，在启动终端按 Ctrl+C，等待服务退出。
后台运行时，在 PowerShell 执行：

```powershell
$serverPid = [int](Get-Content 'E:\qwen-local\qwen-local\logs\qwen8b.pid')
Stop-Process -Id $serverPid
```

## 5. 实验与切换

当前两种模型使用相同的网页、数据库与流式接口。默认仍为 Qwen3-4B NF4。
8B 启动入口指定 LLM.int8()，异常值阈值 6.0，不启用 CPU 卸载。
INT8 路径的未量化浮点模块使用 FP16，避免当前 bitsandbytes 对 BF16 输入反复转换和打印提示。
INT8 配置不改变 KV Cache 精度；后续需单独实现 KV 量化或裁剪。

现有程序每次只取最近 20 条消息，并最多保留 6144 个输入 token，最多生成 2048 token。
输入包含系统提示、历史消息和当前问题，总输入与输出预算为 6656 token。
可通过 QWEN_MAX_INPUT_TOKENS 和 QWEN_MAX_NEW_TOKENS 环境变量调整预算。
所以目前不是完整历史的实验基线；正式比较上下文压缩前，应明确区分现有截断策略。
聊天请求间目前不持久复用 KV，单次 generate 内部会使用默认 KV Cache。

在新终端启动原始入口即可使用 4B 默认配置。若复用 8B 终端，先停止服务，再执行：

```powershell
Remove-Item Env:QWEN_MODEL_PATH -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_QUANTIZATION -ErrorAction SilentlyContinue
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

## 当前验证范围

2026-10-05 已完成权重下载、CUDA INT8 运算检查及真实模型流式生成。
环境：PyTorch 2.11.0+cu128、Transformers 5.17.0、bitsandbytes 0.50.2、Accelerate 1.15.0。

一次短文本生成实测（25 个输入 token，输出预算 512 token，非 thinking，实际提前结束）：
- 确认 252 个 Linear8bitLt 层，模型全部位于 cuda:0。
- 模型常驻占用：8.79 GiB。
- 生成峰值已分配显存：8.88 GiB；峰值已保留显存：9.06 GiB。
- 首个文本片段延迟：0.71 秒；总耗时：19.70 秒。

这些数据仅是一次短文本部署验证，不代表长上下文、并发容量或任务质量评测。
已启动后台服务，并通过健康检查、HTML 页面、真实 SSE 生成、回答数据库保存验证。
自动验证创建的临时对话已删除。
前端模型名称通过健康检查动态显示，不再固定标注 4B。

### Markdown 显示

助手回答支持 Markdown 标题、加粗、列表、引用、代码块和表格。
流式增量与历史记录使用同一渲染入口，数据库仍保存原始 Markdown 文本。
用户消息按纯文本显示。渲染库与 HTML 清理库位于 frontend/vendor，页面使用时无需联网。
前端变更刷新页面即可生效，不需要重启模型。已通过真实流式回答及刷新后历史排版验证。

### 2026-10-05 上下文上限调整

普通与流式接口统一设置输入上限 6144 token，输出预算保持 512 token。
使用原始 9605 token 的重复案件文本测试，日志确认截断后实际输入为 6144 token。
真实 SSE 请求成功结束，模型返回“已阅读。”，总耗时约 4.59 秒。
采样整卡显存占用峰值约 23.22 GiB，包含系统及 PyTorch 保留显存，不等同于模型实际分配量。
此前 8192 token 压力测试接近整卡容量且长时间未返回，故选择 6144 作为当前默认。
该测试不是长文理解质量或 512 token 满长度输出验证，也不保证任意长输入具有相同速度。
临时测试对话与测试脚本已清理。健康检查可查看 max_input_tokens 和 max_new_tokens。

参考：
- https://huggingface.co/Qwen/Qwen3-8B
- https://huggingface.co/docs/transformers/quantization/bitsandbytes
- https://huggingface.co/docs/huggingface_hub/guides/download


### 输出预算与请求统计（当前配置）

默认输入 6144、输出 2048 tokens；旧的 512 输出预算容易截断长文。
Token 不等于汉字，2048 只是上限，不能保证模型恰好写出 1000 字。
可在启动前通过 QWEN_MAX_NEW_TOKENS 环境变量覆盖，修改后须重启服务。

普通接口与 SSE done 事件均返回 metrics；控制台输出统计，网页在新回答下显示指标。
网页指标暂不写入数据库，刷新后历史回答仍保留，指标不会保留。
- output_tokens：实际生成 token ID 数，包含 EOS 等特殊 token；不是重新分词文本得到的估计。
- finish_reason：stop 正常结束，length 输出达到上限，cancelled 取消，error 生成失败。
- ttft_seconds：模型生成阶段开始至第一个生成 token 进入 streamer，包含预填充。
- request_ttft_seconds：服务端进入处理函数至首 token，包含数据库、准备和排队。
- tokens_per_second：(输出 tokens - 1) / (末 token 时间 - 首 token 时间)，排除首 token 等待；单 token 返回 null。
- generation_seconds：整个 model.generate 时间，包含预填充和收尾；queue_seconds 单独列出。
- end_to_end_seconds：服务端开始处理至回答入库、准备发出 done，不包含浏览器网络与渲染。
- gpu_used_gib / gpu_used_percent：CUDA mem_get_info 在结束时报告的整卡占用快照；不是 GPU 计算利用率，也不是整卡峰值。
- peak_allocated_gib / peak_reserved_gib：获取生成锁后重置统计，本次请求 PyTorch 已分配/保留峰值，包含常驻权重；不是 KV cache 单独大小。

这些指标供部署观察。严谨消融实验应固定提示、输入/输出长度、随机种子和并发，预热后重复测量；PyTorch 保留池会受之前请求影响。


真实验证：161 输入 tokens，732 输出 tokens，finish_reason=stop。
回答包含六节与总结，原始文本 1266 字符，其中 1096 个汉字，超过原 512 输出上限后仍完整结束。
该次冷启动后的请求：首 token（服务端含排队）0.79s、decode 8.07 token/s、服务端端到端 91.40s；
结束时整卡占用 10.74 / 23.99 GiB（44.77%），PyTorch 峰值已分配 8.97 GiB、保留 9.12 GiB。
这仅代表该提示的一次结果。普通非流式接口也验证了回答和 metrics 正常返回。
