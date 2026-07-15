export default function Home() {
  return (
    <main>
      <p className="eyebrow">AI TECH RADAR</p>
      <h1>每日 AI 技术动态，正在建立信号。</h1>
      <p className="intro">
        平台基础环境已经就绪。接下来将接入 arXiv、GitHub Releases 与 Hugging Face，聚合同一技术事件的多方信息。
      </p>
      <div className="status" role="status">
        <span aria-hidden="true" />
        MVP foundation online
      </div>
    </main>
  );
}
