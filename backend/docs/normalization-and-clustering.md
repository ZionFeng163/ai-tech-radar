# 资讯规范化、去重与事件聚类

处理流水线只读取尚未关联 `Article` 的 `RawItem`。每条原始记录会先完成 URL、标题、作者
和标签规范化，再通过精确身份选择或创建统一 `Article`，最后加入时间窗口内最相似的
`EventCluster`。

## 运行方式

先执行数据库迁移，再处理当前未关联的原始记录：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli normalize
```

调试时可用 `--limit 20` 控制数量。流水线使用独立的 PostgreSQL advisory lock；并发触发时
只有一个进程处理，其余调用返回 `skipped: true`。

## 精确去重

每个 Article 可拥有多个 `ArticleIdentity`：

- `source_external_id`：来源 slug 与稳定外部 ID
- `canonical_url`：移除 fragment、跟踪参数、默认端口并排序 query 后的 URL；arXiv PDF、
  版本化 abs URL 会归一到无版本 abs URL
- `title_fingerprint`：Unicode NFKC、HTML entity 解码、大小写和标点归一后的 SHA-256；
  Release 和模型/数据集会额外包含仓库作用域，避免不同项目的同名版本误合并

身份表使用 `(identity_type, identity_hash)` 唯一约束，避免长 URL 直接进入唯一索引。重复运行
只会跳过已绑定 Article 的 RawItem；同一精确身份的新来源记录会关联既有 Article，并继续通过
RawItem 保留来源、原始 payload 和来源元数据。

## 相似事件聚类

新 Article 的标题（可配置附加正文前缀）会转换为固定维度的 `feature_hash_v1` embedding。
特征包含规范化词、轻量英文词干、相邻词和字符三元组；整个过程本地、确定性运行，不依赖
外部模型服务。

流水线只比较 `event_window_hours` 时间窗内的候选 cluster，并计算余弦相似度。达到
`similarity_threshold` 时加入最佳 cluster，否则新建 cluster。`EventCluster` 保存：

- centroid 与 Article 成员数
- 首次和最近发布时间
- embedding 方法与使用阈值
- 最近一次匹配分数、共同词和标题

默认参数位于 [`../config/processing.json`](../config/processing.json)。阈值不是线上写死值，可根据
评估结果独立调整。

## 离线评估

样本位于 [`../config/evaluation/dedup-samples.json`](../config/evaluation/dedup-samples.json)，包含
同事件和不同事件标题对。运行：

```bash
docker compose exec backend python -m app.cli normalize --evaluate
```

输出每组相似度、预测结果，以及 precision、recall 和 F1。默认样本用于回归保护，不代表完整
生产语料；新增来源或调整阈值时应扩充样本。
