import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main-content" className="state-page shell">
      <p className="kicker">404 / SIGNAL LOST</p>
      <h1>这条信号不在雷达上。</h1>
      <p>它可能已被合并、移除，或链接已经失效。</p>
      <Link className="action-button" href="/">返回今日信号</Link>
    </main>
  );
}
