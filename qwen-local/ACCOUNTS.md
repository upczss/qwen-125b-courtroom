# 本地多用户版本

访问 http://127.0.0.1:8000，首次点击注册，创建自己的账号。用户名为3–32位字母/数字/下划线（保存为小写），密码8–128位。
注册成功自动登录，退出后可以重新登录。两个不同账号测试请使用普通窗口和隐私窗口，或两个不同浏览器；同一浏览器普通标签页共享登录Cookie。

聊天数据现存 PostgreSQL。旧 data/chat.db 测试记录不迁移、不删除、不再读取。
DBeaver 刷新 qwen/public，可查看 users、conversations、messages、alembic_version。
密码以 Argon2id 哈希保存，Redis 保存随机凭证的 SHA256 索引及用户ID，不保存明文密码。
登录有效期24小时，退出删除Redis登录会话；Redis不可用时认证失败关闭访问。
登录/注册同一来源IP五分钟最多30次，代理部署前需要调整来源IP信任与限流策略。
本机 HTTP Cookie 为 HttpOnly / SameSite=Strict；正式 HTTPS 部署须配置 COOKIE_SECURE=true。
写操作限制同源 Origin、拒绝跨站请求并要求JSON。当前允许 localhost:8000 与 127.0.0.1:8000，上线域名需调整配置。
会话列表、读取、删除、普通及流式消息接口均在服务端验证用户归属，越权返回404。

启动顺序：

```powershell
cd E:\qwen-local\qwen-local\deploy\local
docker compose up -d --wait
docker compose -f compose.inference.yaml up -d
cd E:\qwen-local\qwen-local
& 'D:\Anaconda\envs\qwen-local-new\python.exe' -m alembic upgrade head
& 'D:\Anaconda\envs\qwen-local-new\python.exe' serve_vllm.py
```

依赖固定在 requirements-web.txt，数据库连接默认读取 deploy/local/.env 的 PostgreSQL 密码。可通过 DATABASE_URL / REDIS_URL 覆盖。
暂时一个业务worker、最多五个生成请求和五个等待位置，每账号一个请求；队列超时120秒。会话占用仍在进程内管理，不支持横向扩展。
当前没有管理员管理、找回密码、邮箱验证或审计日志；这是本地多用户基础版，上线前还需部署和进一步完善。

验收：未登录401，注册/登录/重复注册，Cookie属性，跨账号读取/删除/两类生成拒绝，同源防护，退出后旧凭证失效，重新登录历史保留，双账号流式输出重叠并分别入库。
测试脚本 deploy/local/test_accounts.py；通过真实本地服务测试后清理自己的临时账号和会话。
网页登录/注册模式已在浏览器检查。测试账号不作为预置用户保留。
