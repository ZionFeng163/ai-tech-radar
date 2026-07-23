# AI Tech Radar

AI Tech Radar 是一个每日深度学习与 AI 技术资讯平台。项目会从多个来源采集内容，经过规范化、去重、事件聚类和结构化分析后，通过 Web 界面提供浏览与检索能力。

当前阶段只实现可本地运行、可重复采集、可浏览的 MVP。

## 技术栈

- 后端：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、Pydantic 2
- 数据：PostgreSQL 16、Redis 7
- 前端：Next.js、React、TypeScript、App Router
- 运行：Docker Compose
- 质量：pytest、ruff、mypy、Vitest、ESLint

## 仓库结构

```text
backend/   FastAPI 服务、数据库模型与采集处理逻辑
frontend/  Next.js Web 应用
infra/     基础设施说明与后续部署配置
```

## 快速启动

要求已安装 Docker Desktop，并确保 3000、8000、5432、6379 端口可用。

```bash
cp .env.example .env
make dev
```

首次构建需要下载容器镜像和项目依赖。启动完成后访问：

- Web 首页：http://localhost:3000
- 后端健康检查：http://localhost:8000/health
- OpenAPI 文档：http://localhost:8000/docs

停止服务：

```bash
make down
```

## 本地质量检查

后端要求 Python 3.12，前端要求 Node.js 20 以上。

```bash
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

cd ../frontend
npm ci

cd ..
make lint
make test
```

统一质量门禁包含后端 Ruff、mypy、pytest，以及前端 ESLint、TypeScript、Vitest 和生产构建。
执行最小端到端验收时，会启动一套隔离的临时 Docker Compose 环境，不会修改日常开发数据库：

```bash
make e2e
```

该命令依次执行数据库迁移、写入确定性样例资讯、查询列表和搜索 API，并验证首页、详情页及
社交分享资源可访问。失败时返回非零状态并输出后端、前端最近日志。完整本地门禁可运行
`make ci` 后再运行 `make e2e`。

GitHub Actions 会在 Pull Request 和 `main` 分支推送时自动执行后端、前端与端到端三组检查，
配置见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

## 配置

本地配置从 `.env` 读取，所有可用变量及开发默认值见 `.env.example`。不要提交真实密钥或本地 `.env`。

## 数据模型与迁移

所有来源数据先写入 `RawItem`，再规范化为 `Article`。同一来源下的稳定外部 ID 具有唯一约束，来源特有字段保存在 JSONB 中。详细设计见 [`backend/docs/data-model.md`](backend/docs/data-model.md)。

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

## arXiv 采集样例

采集最多 3 篇论文并幂等写入 `RawItem`：

```bash
docker compose exec backend python -m app.sources.arxiv.sample --limit 3 --persist
```

分类、关键词、时间窗口、分页、限流、重试和增量游标的详细说明见
[`backend/docs/arxiv-collector.md`](backend/docs/arxiv-collector.md)。

## GitHub Releases 采集样例

默认配置包含 10 个 AI 项目仓库。以下命令匿名采集最多 3 条 Release 并幂等写入：

```bash
docker compose exec backend python -m app.sources.github_releases.sample --limit 3 --persist
```

设置 `GITHUB_TOKEN` 可使用认证额度；未设置时自动降级为公开仓库匿名访问。仓库、组织、
主题发现、ETag 游标和限流策略见
[`backend/docs/github-releases-collector.md`](backend/docs/github-releases-collector.md)。

## Hugging Face 采集样例

采集近期更新的模型和数据集并幂等写入 `RawItem`：

```bash
docker compose exec backend python -m app.sources.hugging_face.sample --limit 3 --persist
```

默认支持 `text-generation`、`image-text-to-text`、`automatic-speech-recognition`，并可按
作者、组织和数据集标签筛选。设置 `HF_TOKEN` 可使用认证请求；详细游标、限流和异常隔离
规则见 [`backend/docs/hugging-face-collector.md`](backend/docs/hugging-face-collector.md)。

## 手动生成雷达期次

首页的“手动抓取新一期”会依次采集已注册来源，完成规范化、去重和低成本概览，
并保存为不可变的雷达期次。首页日期选择器使用手动抓取时间，不使用技术发布时间；
技术发布时间仍作为文章元数据显示。

默认优先抓取经过社区排序的免费来源：

- Hacker News Top Stories：排名、投票数和评论数。
- DEV Community 近 7 日热门：摘要、标签、公开反应数和评论数。
- Lobsters 前台 RSS：聚焦计算机主题的社区投票流。

同时少量保留 GitHub Releases、arXiv 和 Hugging Face 作为原始技术信号。社区来源的
互动数据会进入快速概览的热度判断，不需要密钥；单次手动抓取对原始来源使用更小配额。

也可以仅调试单个来源：

```bash
docker compose exec backend python -m app.cli collect --source arxiv --limit 3
```

Compose 不启动定时采集服务。统一运行器仍记录 `FetchRun` 状态和统计，使用指数退避重试，
并以 PostgreSQL 来源级 advisory lock 阻止并发抓取。

## 资讯规范化、去重与事件聚类

将尚未处理的 `RawItem` 转为统一 `Article`，并按精确身份和相似事件聚合：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli normalize
```

URL/标题规范化、身份索引、本地特征 embedding、可配置聚类阈值和离线评估说明见
[`backend/docs/normalization-and-clustering.md`](backend/docs/normalization-and-clustering.md)。

## AI 分类、中文摘要与评分

对规范化后的文章使用阿里云百炼 `deepseek-v4-flash` 运行版本化结构分析：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli analyze --limit 10
docker compose exec backend python -m app.cli analyze
docker compose exec backend python -m app.cli analyze \
  --config config/analysis-offline.json --evaluate
```

百炼密钥通过 `DASHSCOPE_API_KEY` 注入；Prompt、模型、重试、原始响应审计和 50 条人工
评测集的说明见 [`backend/docs/ai-analysis.md`](backend/docs/ai-analysis.md)。

## 资讯查询 API

后端提供 `/articles`、`/articles/{id}`、`/topics`、`/daily-brief` 和 `/search`，支持组合筛选、
游标分页、全文检索及查询耗时指标。接口契约与示例见
[`backend/docs/query-api.md`](backend/docs/query-api.md)。

## Web 前端

Next.js 前端通过服务端渲染访问查询 API，提供首页信号流、组合筛选、技术分类、全文搜索和
文章深度分析详情页。Docker 内部使用 `API_URL=http://backend:8000`，浏览器侧公开地址使用
`NEXT_PUBLIC_API_URL=http://localhost:8000`；本地启动后访问 http://localhost:3000。

```bash
cd frontend
npm test
npm run lint
npm run typecheck
npm run build
```
