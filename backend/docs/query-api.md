# 资讯查询 API

FastAPI 提供文章列表、详情、分类聚合、每日简报和全文搜索接口。开发环境启动后可访问：

- OpenAPI JSON：`http://localhost:8000/openapi.json`
- Swagger UI：`http://localhost:8000/docs`

## 接口

### `GET /articles`

按发布时间倒序返回文章，支持以下查询参数：

| 参数 | 含义 |
| --- | --- |
| `date_from` / `date_to` | UTC 发布日期范围，首尾日期均包含 |
| `source` | 来源 slug，如 `arxiv`、`github-releases`、`hugging-face` |
| `category` | 主技术分类 |
| `importance_min` | 最低重要性评分，0 至 10 |
| `open_source_status` | `open`、`partial`、`closed` 或 `unknown` |
| `limit` | 每页 1 至 100 条，默认 20 |
| `cursor` | 上一页返回的 opaque cursor |

```bash
curl 'http://localhost:8000/articles?category=foundation_models&importance_min=7&limit=20'
```

响应的 `page` 包含 `has_more`、`next_cursor` 和 `query_ms`。客户端不应解析或修改 cursor；
存在下一页时，把 `next_cursor` 原样传给下一次请求。

### `GET /articles/{id}`

返回文章正文、结构化分析、作者、原始来源引用和分析版本。不存在时返回 404。

### `GET /topics`

按 `primary_category` 聚合文章数量、平均重要性和最近发布时间。支持日期、来源、最低重要性和
开源状态筛选。

### `GET /daily-brief`

返回指定日期的文章总数、分类分布和按重要性排序的重点文章：

```bash
curl 'http://localhost:8000/daily-brief?date=2026-07-19&limit=10'
```

日期边界使用 `BRIEF_TIMEZONE`，默认 `Asia/Shanghai`。还可按来源、分类、最低重要性和开源
状态筛选。

### `GET /search`

使用 PostgreSQL `websearch_to_tsquery` 搜索标题、摘要和正文，英文查询走 GIN 全文索引，中文
查询增加子串匹配回退。结果按相关性、发布时间和 UUID 稳定排序，并支持与 `/articles` 相同的
筛选和 cursor 分页。

```bash
curl 'http://localhost:8000/search?q=transformer&source=arxiv&limit=20'
```

## 性能与索引

所有响应都包含：

- `Server-Timing: app;dur=<milliseconds>`
- `X-Response-Time-Ms: <milliseconds>`

分页响应和聚合响应还包含 `query_ms`。迁移 `0004_article_search_indexes` 创建：

- `(published_at, id)` B-tree 列表/游标索引
- `raw_items(article_id)` 来源关联索引
- 标题、摘要、正文的 `simple` 配置 GIN 全文索引

项目的 PostgreSQL 集成测试对核心查询设有 1 秒基础上限。运行方式：

```bash
cd backend
RUN_DATABASE_TESTS=1 \
DATABASE_URL=postgresql+psycopg://radar:radar@localhost:5432/radar \
.venv/bin/python -m pytest tests/test_api.py
```

测试数据在外层事务中创建并回滚，不污染开发数据库。
