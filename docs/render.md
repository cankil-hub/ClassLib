# Render Free 部署

Render 与 Vercel 共用 `production` 分支以及现有 Supabase 数据库和私有对象存储。
账号、密码与资料保持同步，不要导入 SQLite 或重新初始化线上数据库。

在 Render 创建 Python Web Service，选择 GitHub 仓库和 `production` 分支，
区域 Singapore、实例 Free。`render.yaml` 提供配置参考及 Blueprint 定义。

- Build: `pip install -r requirements-render.txt && python manage.py collectstatic --noinput`
- Start: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120 --access-logfile -`
- Health check: `/login/`
- `DJANGO_SETTINGS_MODULE=config.render`
- 将现有生产 `DJANGO_SECRET_KEY`、`DATABASE_URL` 和五个 `S3_*` 配置保存到 Render 环境变量。
- 数据库使用 Supabase 6543 事务池连接，保留 SSL。

Render 自动提供 `RENDER_EXTERNAL_HOSTNAME`，用于允许访问的域名与 CSRF 来源。
WhiteNoise 提供构建时收集的 CSS/JS；账号和上传文件不保存在 Render 临时磁盘。
自定义域名需要另行配置 `DJANGO_ALLOWED_HOSTS` 和 HTTPS `DJANGO_CSRF_TRUSTED_ORIGINS`。

构建不执行数据库迁移。后续需要升级表结构时，先备份，使用项目现有的
`scripts/migrate_production.py` 流程维护 Supabase 表权限与 RLS。

免费实例闲置后会休眠。默认域名的国内可达性需要在实际使用的网络上测试。
PDF 下载仍访问 Supabase，网站能打开不代表文件下载链路一定畅通。
