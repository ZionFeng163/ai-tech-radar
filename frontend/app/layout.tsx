import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SiteHeader } from "@/components/site-header";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL ?? "http://localhost:3000"),
  title: {
    default: "AI Tech Radar｜每日 AI 技术信号",
    template: "%s｜AI Tech Radar",
  },
  description: "聚合论文、开源项目、模型与数据集，用中文解释每天真正重要的 AI 技术进展。",
  openGraph: {
    title: "AI Tech Radar｜每日 AI 技术信号",
    description: "把每天的 AI 噪声，压缩成值得追踪的信号。",
    locale: "zh_CN",
    siteName: "AI Tech Radar",
    type: "website",
    images: [{
      url: "/og.png",
      width: 1200,
      height: 630,
      alt: "AI Tech Radar 雷达信号封面",
    }],
  },
  twitter: {
    card: "summary_large_image",
    title: "AI Tech Radar｜每日 AI 技术信号",
    description: "把每天的 AI 噪声，压缩成值得追踪的信号。",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <a className="skip-link" href="#main-content">
          跳到主要内容
        </a>
        <SiteHeader />
        {children}
        <footer className="site-footer shell">
          <div>
            <span className="brand-mark" aria-hidden="true">ATR</span>
            <strong>AI Tech Radar</strong>
          </div>
          <p>每日扫描 · 深度分析 · 独立判断</p>
          <p>Built for people who build AI.</p>
        </footer>
      </body>
    </html>
  );
}
