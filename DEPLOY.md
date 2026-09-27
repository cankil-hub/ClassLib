# ClassLib：本地分支与正式部署

## 分支约定

| 分支 | 默认配置 | 数据库 | 文件存储 |
| --- | --- | --- | --- |
| `local` | `config.local` | 本地 SQLite | `private_files/` |
| `production` | `config.production` | Supabase PostgreSQL | Supabase 私有 Storage |

两个分支共用全部业务代码。唯一有意保留的代码差异是
`config/environment.py` 的 `DEFAULT_SETTINGS_MODULE`。
环境变量 `DJANGO_SETTINGS_MODULE` 可显式覆盖分支默认值。
不要把生产 `.env` 留在本地测试环境中；`.env`、`.env.*`（示例除外）和 `.vercel/` 不进入 Git。

日常开发与发布：

```powershell
git switch local
# 开发完成后运行测试、提交
.\.venv\Scripts\python.exe manage.py test --settings=config.local
git push origin local
git switch production
git merge local
# 确认 environment.py 仍为 config.production
git push origin production
git switch local
```

不要把 `production` 反向合并到 `local`，也不要日常编辑分支默认配置文件。
`main` 保留原版，Vercel 的 Production Branch 必须设置为 `production`。
`vercel.json` 已关闭 `local` 和 `main` 的自动部署。

## 代码边界

- `accounts/`：账号、登录与角色。
- `library/`：目录、文件元数据、搜索、权限、校验和上传流程。
- `storage_backends/base.py`：存储接口与统一异常。
- `storage_backends/local.py`：本地磁盘实现。
- `storage_backends/s3.py`：Supabase S3 协议实现；只有这里依赖 boto3。
- `config/local.py`、`config/production.py`：环境配置。

业务层通过 `get_storage()` 获取适配器，不包含 Supabase URL、密钥或 SDK 调用。
保留 Django 账号体系，不需要接入 Supabase Auth。

## 1. Supabase

1. 创建项目，记录区域和数据库密码。
2. `Connect` 中复制 Transaction pooler 连接串供 Vercel 使用；
   本地数据库迁移使用 Session pooler 连接串（IPv4 可用）。密码中的保留字符需要 URL 编码。
3. 创建名为 `classlib-files` 的 **Private** bucket，设置单文件上限 50 MiB
   （52428800 字节，且不能超过账号计划允许的上限）。不要开启 Public。
4. 在 Storage 的 S3 连接设置启用 S3，获取 endpoint、region、Access Key ID、Secret Access Key。
   这里使用的是 **S3 凭据**，不是 Supabase REST API 的 `sb_secret_...`。
5. 本项目直接通过 Django ORM 访问数据库，不使用 Data API。
   在项目 API 设置中关闭不需要的 Data API，防止 Django 用户/会话表经 API 暴露。
   如果此 Supabase 项目还供其他应用使用，不要贸然关闭它；将本应用放到专用项目或非公开 schema。

S3 密钥只保存在服务端。本项目后端负责权限检查，浏览器只获得某个随机暂存对象的短期签名地址。
Supabase 的 S3 API 不支持 AWS `PutBucketCors`，不要套用 AWS CORS 配置命令；
部署验收需要实际验证浏览器 PUT 的预检与上传结果。

## 2. Vercel

1. 从 GitHub 导入 `cankil-hub/ClassLib`，根目录为仓库根，框架选择 Django。
2. 设置 Production Branch 为 `production`；`vercel.json` 将函数区域固定为新加坡 `sin1`，靠近本项目 Supabase 数据库。
3. 在 **Production** 环境填写 `.env.production.example` 的全部变量，
   `DJANGO_SETTINGS_MODULE=config.production`。
4. `DJANGO_ALLOWED_HOSTS` 使用实际稳定网站域名（不带协议）；
   `DJANGO_CSRF_TRUSTED_ORIGINS` 使用 `https://` 开头的完整来源，多个值用逗号分隔。
5. 使用随机密钥，例如本地执行
   `.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`。
   密钥只粘贴到受保护的环境配置中，不要发到聊天、写进代码或提交 Git。
6. 默认构建即可；Vercel 会发现 `manage.py`/WSGI 并自动执行 `collectstatic`。
   不要把 `runserver` 作为构建命令，不要在每个 Web 请求或并行构建里自动执行数据库迁移。
7. Preview 如有需要，使用另一套数据库和 bucket，不能连接班级正式数据。

Python 版本由 `.python-version` 指定为 3.13。
Vercel 的 4.5 MB 请求限制要求浏览器直传；本项目云端不会接收大文件 multipart 请求。

## 3. 数据库初始化与管理员

在受信任电脑中将 `.env.production.example` 复制为 `.env` 并填入真实配置，
其中 `DATABASE_URL` 此时使用 Session pooler。执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py check --deploy --settings=config.production
.\.venv\Scripts\python.exe scripts/migrate_production.py
.\.venv\Scripts\python.exe manage.py createsuperuser --settings=config.production
```

管理员在终端交互创建，不在公开页面提供初始化接口。
正式数据库迁移使用 `scripts/migrate_production.py`：它在一个事务中运行迁移，
取消当前迁移角色对新表的匿名 API 默认授权，并为 Django 表启用 RLS、撤销
`anon`、`authenticated` 和 `PUBLIC` 的表/序列权限。Django 的数据库角色仍可正常访问。
该脚本用于此应用的专用 PostgreSQL 项目；非原子迁移会被拒绝，需单独制定发布步骤。
初始化完成后，恢复本地 `.env` 为 `config.local` 或移走生产配置；
Vercel 继续使用 Transaction pooler。
已有 SQLite 数据和 `private_files/` 不会自动复制到 Supabase，需要另行迁移。

## 4. 上传、下载和清理

上传：教师鉴权 → 创建 UploadIntent → 签名 PUT 到 `pending/` →
服务端复制到浏览器无权写入的 `files/` → 校验实际大小和文件内容 → 提交 File 记录。
完成接口绑定上传者，并校验到期时间、目标文件夹与名称冲突，支持重复确认。
复制后再校验，防止重用上传链接篡改已发布文件。

当前采用单次 PUT（含进度显示），网络失败需要重新传输文件；
完成确认失败可以直接重试确认。尚未实现断点续传。
校验阶段会从对象存储读取文件到有大小上限的临时缓冲区，最大 50 MiB，
不会通过浏览器响应返回文件。部署后需验证大文件的耗时是否满足 120 秒函数时限。

下载：Django 鉴权后跳转至有效期 60 秒的签名下载链接。
有效期内拿到链接的人仍能下载，因此不要公开分享这些链接。

文件删除和存储删除之间用持久化队列协调，存储故障不丢失待删除记录。
过期上传保留一天余量后可清理，防止未结束的 PUT 与清理冲突。
在安全管理终端或你自己的计划任务中定期执行以下命令，建议每日一次：

```powershell
# 先预览数量
.\.venv\Scripts\python.exe manage.py cleanup_uploads --settings=config.production
.\.venv\Scripts\python.exe manage.py cleanup_objects --settings=config.production
# 确认后执行清理
.\.venv\Scripts\python.exe manage.py cleanup_uploads --apply --settings=config.production
.\.venv\Scripts\python.exe manage.py cleanup_objects --apply --settings=config.production
```

上传清理只删除过期授权关联的暂存对象和未完成对象，不扫描整个 bucket；
已完成文件的正式对象不会被清理。清理命令未自动配置到云端计划任务。

## 验收

- 登录、创建账号、停用账号、修改密码。
- 本地上传仍然可用，云端上传大小覆盖小文件和大于 4.5 MB 的文件。
- 学生可下载，不能创建上传凭证或确认上传；未登录者不能查看文件。
- 伪造扩展名、大小不符、过期授权、重复文件名和其他人的上传凭证被拒绝。
- 重新部署后账号、文件列表和对象仍然存在。
- 私有 bucket 的未签名地址不可访问，JS 不包含数据库密码或 S3 Secret。
- 手机实际网络访问和浏览器上传的跨域请求正常。

官方参考：
- https://vercel.com/docs/frameworks/full-stack/django
- https://vercel.com/docs/functions/limitations
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/docs/guides/storage/s3/authentication
- https://supabase.com/docs/guides/storage/s3/compatibility
