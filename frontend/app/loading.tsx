export default function Loading() {
  return (
    <main id="main-content" className="state-page shell" aria-busy="true">
      <p className="kicker">SCANNING THE HORIZON</p>
      <h1>正在同步技术信号…</h1>
      <div className="loading-lines" aria-hidden="true"><span /><span /><span /></div>
    </main>
  );
}
