# AI 结构化分析

规范化后的 `Article` 由可替换的 Analysis Provider 生成中文摘要、技术分类、标签、核心创新、
与已有工作的差异、应用场景、开源状态、可信度、重要性和关注理由。

## 输出契约

- Pydantic 契约：`app/analysis/schema.py` 中的 `ArticleAnalysisV1`
- 固化 JSON Schema：`config/schemas/article-analysis-v1.json`
- 当前 `schema_version`：`1.0`
- 未声明字段会被拒绝，评分范围固定为 0 至 10

每篇文章的当前结果写入 `articles.analysis`，常用筛选字段同时写入独立列。每次调用均新增
`analysis_runs` 记录，包含 Provider、模型、Prompt/Schema 版本、尝试次数、完整请求、原始响应、
解析结果或错误。失败尝试不会被后续重试覆盖。

## Provider 与配置

默认生产配置使用阿里云百炼的 `deepseek-v4-flash`。百炼密钥只通过环境变量注入：

```json
{
  "provider": "bailian",
  "model": "deepseek-v4-flash",
  "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key_env": "DASHSCOPE_API_KEY",
  "prompt_path": "config/prompts/article-analysis-v1.txt",
  "prompt_version": "article-analysis-v1",
  "max_attempts": 3,
  "retry_backoff_seconds": 1,
  "timeout_seconds": 60,
  "max_input_characters": 12000,
  "max_output_tokens": 2000
}
```

百炼 Provider 使用 OpenAI 兼容 Chat Completions 的 JSON 模式并关闭思考模式，返回内容继续由
本地 `ArticleAnalysisV1` 严格校验。密钥只从 `DASHSCOPE_API_KEY` 读取，不进入配置、请求审计
或数据库。北京公共端点支持跨业务空间 API Key；生产环境也可将 `api_base` 改为业务空间专属
域名以获得更好的隔离与吞吐。

端点、地域和模型能力以阿里云百炼官方的
[Base URL 总览](https://help.aliyun.com/zh/model-studio/base-url)与
[DeepSeek API 文档](https://help.aliyun.com/zh/model-studio/deepseek-api)为准。

`deterministic` Provider 无需网络或密钥，适合 CI 和数据链路验收。它遵守同一 Schema，但不是
生产内容质量的替代品，配置位于 `config/analysis-offline.json`。

Prompt 位于 `config/prompts/article-analysis-v1.txt`，内容与版本号分别配置。修改 Prompt 后使用
`--force` 重新分析；提升 Schema 版本后，旧版本文章会自动重新进入待处理队列。

## 运行

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli analyze --limit 10
docker compose exec backend python -m app.cli analyze --force --limit 10
docker compose exec backend python -m app.cli analyze --schema
```

同一时间只允许一个分析进程持有 PostgreSQL advisory lock。文章之间失败隔离；429、5xx、网络
异常和 Schema 校验失败按指数退避重试，非重试型 4xx 直接结束当前文章。

## 人工评测集

`config/evaluation/analysis-samples.json` 包含 50 条人工标注样本，覆盖全部技术分类与四种开源
状态。离线回归命令：

```bash
docker compose exec backend python -m app.cli analyze \
  --config config/analysis-offline.json --evaluate
```

输出 Schema 合法率、主分类准确率、开源状态准确率、重要性评分区间准确率和逐条错误。
