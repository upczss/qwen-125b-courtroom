# 实验组公网访问

公网地址：https://zss.nat200.top/

NATAPP配置：Web隧道，绑定zss.nat200.top，开启域名HTTPS，本地127.0.0.1:8000，本地HTTPS关闭，Host Header留空。

## 启动

先启动 Docker Desktop、PostgreSQL、Redis，并保持 Strata 在 127.0.0.1:8080 运行。检查 /health 的 loaded 为 true。当前使用 Strata IQ2_XS，无需启动旧 vLLM 容器；详细步骤见 STRATA_SWITCH.md。

停止旧的8000后端（在它的窗口按Ctrl+C），然后在PowerShell执行：

```powershell
cd E:\qwen-local\qwen-local
& 'D:\Anaconda\envs\qwen-local-new\python.exe' -m alembic upgrade head
& 'D:\Anaconda\envs\qwen-local-new\python.exe' serve_public.py
```

保持此窗口打开。公网模式只允许HTTPS公网域名的网页写请求，并为登录Cookie设置Secure。浏览器请使用公网HTTPS地址登录聊天；若要恢复本机HTTP使用，停止它后改运行serve_vllm.py。两者不能同时占用8000。

## NATAPP客户端

在natapp.exe所在目录创建config.ini，内容如下；将占位符替换为控制台中自己的authtoken，不要分享此文件或密钥：

```ini
[default]
authtoken=在这里填写自己的隧道密钥
```

进入客户端目录后执行：

```powershell
.\natapp.exe
```

保持窗口运行，确认连接成功并显示分配的域名。不要将密钥放到聊天消息或命令参数中。不要把带密钥的配置提交到Git。

## 验收和关闭

用手机关闭Wi-Fi，使用移动网络打开https://zss.nat200.top/，测试登录、发送消息、逐字输出及刷新后历史记录。另一位成员用独立账号同时测试。证书异常时不要绕过警告。

仅开启域名HTTPS不代表HTTP访问自动重定向，请始终分发https链接。公网真实流式输出须穿过隧道验证，不能仅根据本机测试认定通过。

关闭时先等待回答结束，在NATAPP窗口按Ctrl+C停止公网入口，再在后端窗口按Ctrl+C，最后按START_STOP.md停止容器。

当前注册仍开放，已有的每账号一个请求、3生成+5排队限制继续生效。链接持有者可以注册；初期只向实验组分发。认证限流目前是隧道入口共享每五分钟30次，不信任公网传入的来源IP，暂不区分每个成员。

电脑必须保持开机、联网、不休眠；网页数据经过NATAPP中转，模型计算仍在本机。

