# 采集调度与运行记录

统一入口会从来源注册表构建 arXiv、GitHub Releases 或 Hugging Face 适配器，先取得
PostgreSQL advisory lock，再创建一条 `FetchRun`，逐页幂等写入 `RawItem` 并更新来源游标。

## 手工运行

在 Docker Compose 环境中运行一个来源：

```bash
docker compose exec backend python -m app.cli collect --source arxiv
```

调试时可用 `--limit 3` 限制本次最多采集三条；`--max-attempts` 和
`--backoff-seconds` 可覆盖默认的三次指数退避重试。

## 定时运行

`scheduler` 服务读取 [`../config/schedules.json`](../config/schedules.json)。每个来源可使用：

- `trigger: interval` 与 `interval_minutes`
- `trigger: cron` 与标准五段 cron 表达式

时间统一使用 UTC。每个 APScheduler Job 使用稳定的 `collect:<source>` ID，并启用
`replace_existing`、`coalesce` 和 `max_instances=1`。跨 scheduler 进程则由来源级
PostgreSQL advisory lock 拒绝并发运行；获得不到锁的触发会返回 `skipped`，不会创建
虚假的运行记录。

```bash
docker compose up -d --build scheduler
docker compose logs -f scheduler
```

## FetchRun 状态

- `running`：已创建运行记录，正在采集或等待重试
- `success`：来源完成，未返回条目级错误
- `partial`：有效条目已入库，但来源游标携带部分条目错误
- `failed`：达到最大尝试次数后仍失败

记录包含开始/结束时间、前后游标、抓取/写入/跳过数量、错误摘要，以及触发方式、尝试
次数和重试错误。分页写入后立即保存游标，因此进程级重试会从最近一次成功分页继续。

查询最近运行：

```sql
SELECT s.slug, r.status, r.started_at, r.finished_at,
       r.items_fetched, r.items_stored, r.items_skipped,
       r.error_summary, r.metadata
FROM fetch_runs AS r
JOIN sources AS s ON s.id = r.source_id
ORDER BY r.started_at DESC
LIMIT 20;
```
