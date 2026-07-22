# Infrastructure

The repository-level `compose.yaml` defines the local MVP stack:

- PostgreSQL 16
- Redis 7
- FastAPI backend
- Next.js frontend

CI 使用独立 Compose project 与临时数据卷执行端到端验收，避免影响开发环境。运行方式和
质量门禁说明见仓库根目录 README。
