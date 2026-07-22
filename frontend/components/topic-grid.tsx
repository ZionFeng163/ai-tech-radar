import Link from "next/link";

import { categoryLabels, formatScore } from "@/lib/format";
import type { TopicSummary } from "@/lib/types";

export function TopicGrid({ topics }: { topics: TopicSummary[] }) {
  return (
    <div className="topic-grid">
      {topics.map((topic, index) => (
        <Link
          className="topic-card"
          href={`/topics/${topic.category}`}
          key={topic.category}
        >
          <span className="topic-number">{String(index + 1).padStart(2, "0")}</span>
          <strong>{categoryLabels[topic.category]}</strong>
          <span>{topic.article_count} 条信号</span>
          <span>平均重要性 {formatScore(topic.average_importance)}</span>
        </Link>
      ))}
    </div>
  );
}
