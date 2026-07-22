import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="brand" href="/" aria-label="AI Tech Radar 首页">
        <span className="brand-mark" aria-hidden="true">
          ATR
        </span>
        <span>AI Tech Radar</span>
      </Link>
      <nav className="site-nav" aria-label="主导航">
        <Link href="/">今日信号</Link>
        <Link href="/#topics">技术分类</Link>
        <Link href="/search">搜索</Link>
      </nav>
      <form className="header-search" action="/search" role="search">
        <label className="sr-only" htmlFor="header-q">
          搜索技术资讯
        </label>
        <input id="header-q" name="q" type="search" placeholder="搜索模型、论文、项目…" />
        <button type="submit" aria-label="提交搜索">
          ↗
        </button>
      </form>
    </header>
  );
}
