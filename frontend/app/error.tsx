"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main id="main-content" className="state-page shell">
      <p className="kicker">SIGNAL INTERRUPTED</p>
      <h1>雷达暂时失去连接。</h1>
      <p>数据服务可能正在重启，请稍后重试。</p>
      <button className="action-button" type="button" onClick={reset}>重新扫描</button>
    </main>
  );
}
