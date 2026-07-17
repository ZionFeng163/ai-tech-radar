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
