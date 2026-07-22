import type { ArticleKind, OpenSourceStatus, TechnicalCategory } from "./types";

export const categoryLabels: Record<TechnicalCategory, string> = {
  foundation_models: "基础模型",
  training: "训练与微调",
  inference: "推理与部署",
  agents: "智能体",
  multimodal: "多模态",
  computer_vision: "计算机视觉",
  nlp: "自然语言处理",
  speech_audio: "语音与音频",
  robotics: "机器人与具身",
  data: "数据工程",
  evaluation: "评测",
  infrastructure: "AI 基础设施",
  safety: "安全与对齐",
  other: "其他信号",
};

export const kindLabels: Record<ArticleKind, string> = {
  paper: "论文",
  code_repository: "代码",
  release: "版本",
  model: "模型",
  dataset: "数据集",
  blog_post: "博客",
  news: "资讯",
};

export const openSourceLabels: Record<OpenSourceStatus, string> = {
  open: "开源",
  partial: "部分开源",
  closed: "闭源",
  unknown: "未确认",
};

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}

export function formatScore(value: number | null): string {
  return value === null ? "—" : value.toFixed(1);
}
